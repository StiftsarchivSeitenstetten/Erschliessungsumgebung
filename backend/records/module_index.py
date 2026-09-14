"""Rebuildable, field-path-driven indexes. Never a canonical record store."""

from copy import deepcopy
import hashlib
import json
from pathlib import PurePosixPath
import re
import unicodedata

from jsonschema import RefResolver

from ..config import ROOT
from ..github.errors import RepositoryError, RepositoryNotFoundError
from .generic_read import parse_record_file, record_path
from .runtime import RecordRuntime, RecordValidationError


def blob_revision(content):
    data = content.encode("utf-8")
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def index_path(module):
    return (module.storage.get("index") or {}).get("path")


def path_value(value, path):
    parts = path.split(".")

    def walk(current, remaining):
        if not remaining:
            return deepcopy(current)
        if isinstance(current, list):
            return [walk(item, remaining) for item in current]
        if not isinstance(current, dict):
            return None
        return walk(current.get(remaining[0]), remaining[1:])

    return walk(value, parts)


def normalized_text(value):
    """Aggregate canonical scalar values, including structured and repeated data."""
    def tokens(item):
        if item is None:
            return []
        if isinstance(item, dict):
            result = []
            # Both canonical date vocabularies use the same numeric precision.
            for names in (("year", "month", "day"), ("jahr", "monat", "tag")):
                if isinstance(item.get(names[0]), int):
                    date = f"{item[names[0]]:04d}"
                    for key in names[1:]:
                        if item.get(key) is None:
                            break
                        date += f"-{item[key]:02d}"
                    result.append(date)
            for key in sorted(item):
                result.extend(tokens(item[key]))
            return result
        if isinstance(item, list):
            return [token for child in item for token in tokens(child)]
        return [str(item)]

    return " ".join(unicodedata.normalize("NFKC", " ".join(tokens(value))).casefold().split())


class IndexPlan:
    def __init__(self, module):
        self.module = module
        target = index_path(module)
        if target and (PurePosixPath(target).is_absolute() or ".." in PurePosixPath(target).parts or
                       target == (module.storage.get("state") or {}).get("path") or
                       target.startswith(module.storage["data_dir"].rstrip("/") + "/")):
            raise RecordValidationError(["Indexpfad muss ausserhalb von Record- und State-Pfaden liegen."])
        self.columns = [column["path"] for column in module.list_config.get("columns", [])]
        self.fulltext = module.search_config.get("fulltext", [])
        self.lookups = module.search_config.get("lookup", [])
        self.filters = [field["path"] for field in module.search_config.get("filters", [])]
        self.sort = module.list_config.get("default_sort") or module.search_config.get("default_sort") or {"path": "id", "direction": "asc"}
        self.paths = sorted(set(self.columns + self.fulltext + self.lookups + self.filters + [self.sort["path"]]))
        schema = json.loads(module.schema_path.read_text(encoding="utf-8"))
        core = json.loads((ROOT / "schemas/core-datatypes.schema.json").read_text(encoding="utf-8"))
        resolver = RefResolver.from_schema(schema, store={core["$id"]: core})
        for path in self.paths:
            current = schema
            try:
                for part in path.split("."):
                    while "$ref" in current:
                        current = resolver.resolve(current["$ref"])[1]
                    if "items" in current:
                        current = current["items"]
                        while "$ref" in current:
                            current = resolver.resolve(current["$ref"])[1]
                    current = current["properties"][part]
            except (KeyError, TypeError) as exc:
                raise RecordValidationError([f"Ungueltiger Index-Feldpfad: {path}"]) from exc
        self.fingerprint = hashlib.sha256(json.dumps({"paths": self.paths, "columns": self.columns,
            "fulltext": self.fulltext, "lookup": self.lookups, "filters": self.filters, "sort": self.sort,
            "schema": schema}, sort_keys=True).encode()).hexdigest()

    def visible(self, path, role):
        if path == "id":
            return True
        candidates = [field for field in self.module.fields if path == field.path or path.startswith(field.path + ".")]
        return bool(candidates) and max(candidates, key=lambda field: len(field.path)).can_view(role)

    def entry(self, record, revision):
        values = {path: path_value(record, path) for path in self.paths}
        search = {path: normalized_text(values[path]) for path in self.fulltext}
        return {"record_id": record["id"], "revision": revision, "values": values,
                "lookup": {path: normalized_text(values[path]) for path in self.lookups},
                "search": search, "search_text": " ".join(search.values())}


def build_index_entry(module, record, revision):
    return IndexPlan(module).entry(record, revision)


def make_index(module, entries, plan=None):
    plan = plan or IndexPlan(module)
    entries = sorted(entries, key=lambda entry: entry["record_id"])
    ids = [entry["record_id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise RecordValidationError(["Doppelte technische ID im Modulindex."])
    return {"schema_version": 1, "module": module.id, "configuration": plan.fingerprint, "records": entries}


def dump_index(index):
    return json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def build_module_index(module, files):
    plan = IndexPlan(module)
    runtime = RecordRuntime(module)
    entries = []
    for file in files:
        stored = parse_record_file(file)
        try:
            runtime.validate(stored.data)
        except RecordValidationError as exc:
            raise RecordValidationError([f"{file.path}: {error}" for error in exc.errors]) from exc
        if file.path != record_path(module, stored.record_id):
            raise RecordValidationError([f"ID und Dateipfad stimmen nicht ueberein: {file.path}"])
        entries.append(plan.entry(stored.data, blob_revision(file.content)))
    return make_index(module, entries, plan)


def read_module_index(repository, module):
    plan = IndexPlan(module)
    try:
        index = json.loads(repository.read_file(index_path(module)).content)
        if index["schema_version"] != 1 or index["module"] != module.id or index["configuration"] != plan.fingerprint:
            raise ValueError("Indexversion oder Konfiguration veraltet")
        ids = [entry["record_id"] for entry in index["records"]]
        if len(ids) != len(set(ids)):
            raise ValueError("Doppelte IDs")
        for entry in index["records"]:
            if not isinstance(entry["record_id"], str) or not isinstance(entry["revision"], str) or not isinstance(entry["values"], dict) or set(entry["values"]) != set(plan.paths):
                raise ValueError("Ungueltiger Eintrag")
            if set(entry["search"]) != set(plan.fulltext) or set(entry["lookup"]) != set(plan.lookups):
                raise ValueError("Ungueltige Suchfelder")
            if not all(isinstance(value, str) for value in (*entry["search"].values(), *entry["lookup"].values())):
                raise ValueError("Suchwerte muessen Strings sein")
    except (RepositoryNotFoundError, ValueError, KeyError, TypeError) as exc:
        raise RepositoryError("Modulindex fehlt oder ist ungueltig; Rebuild erforderlich.") from exc
    return index


def index_write_files(repository, module, record, content, *, create):
    path = index_path(module)
    if not path:
        return {}
    index = read_module_index(repository, module)
    entry = build_index_entry(module, record, blob_revision(content))
    existing = [item for item in index["records"] if item["record_id"] == record["id"]]
    if create and existing:
        raise RecordValidationError(["Technische ID bereits im Index; Rebuild erforderlich."])
    remaining = [item for item in index["records"] if item["record_id"] != record["id"]]
    return {path: dump_index(make_index(module, remaining + [entry]))}


def rebuild_module_index(repository, module):
    head = repository.get_branch_head()
    path = index_path(module)
    if not path:
        raise RecordValidationError(["Kein Indexpfad konfiguriert."])
    files = repository.list_directory(module.storage["data_dir"])
    extension = module.storage.get("filename", {}).get("extension", ".md")
    index = build_module_index(module, [file for file in files if file.path.endswith(extension)])
    content = dump_index(index)
    try:
        if repository.read_file(path).content == content:
            return index
    except RepositoryNotFoundError:
        pass
    repository.commit_files(expected_head=head, files={path: content}, message=f"Rebuild Modulindex {module.id}")
    return index


def natural_key(value):
    if value is None:
        return (1, ())
    if isinstance(value, (int, float)):
        return (0, ((0, value),))
    if isinstance(value, dict):
        if "from" in value:
            return natural_key(value["from"])
        for names in (("year", "month", "day"), ("jahr", "monat", "tag")):
            if value.get(names[0]) is not None:
                return (0, tuple((0, value.get(key) or 0) for key in names))
        for key in ("value", "name", "code", "id"):
            if key in value:
                return natural_key(value[key])
    return (0, tuple((0, int(part)) if part.isdigit() else (1, part)
                     for part in re.split(r"(\d+)", normalized_text(value)) if part))


def query_index(module, index, role, *, q="", lookup_field=None, lookup_value=None):
    plan = IndexPlan(module)
    if (lookup_field is None) != (lookup_value is None) or (lookup_field is not None and not normalized_text(lookup_value)):
        raise RecordValidationError(["Lookup benoetigt Feld und nichtleeren Wert."])
    if lookup_field is not None and (lookup_field not in plan.lookups or not plan.visible(lookup_field, role)):
        raise RecordValidationError(["Lookup-Feld nicht verfuegbar."])
    terms = normalized_text(q).split()
    entries = []
    for entry in index["records"]:
        text = " ".join(value for path, value in entry["search"].items() if plan.visible(path, role))
        if not all(term in text for term in terms):
            continue
        if lookup_field is not None and entry["lookup"][lookup_field] != normalized_text(lookup_value):
            continue
        entries.append(entry)
    sort_path = plan.sort["path"]
    if not plan.visible(sort_path, role):
        sort_path = "id"
    entries.sort(key=lambda entry: (natural_key(entry["record_id"] if sort_path == "id" else entry["values"][sort_path]), entry["record_id"]),
                 reverse=plan.sort.get("direction") == "desc")
    return [{"record_id": entry["record_id"],
             "values": {path: entry["values"][path] for path in plan.columns if plan.visible(path, role)},
             "meta": {"revision": entry["revision"]}} for entry in entries]
