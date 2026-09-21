"""Guarded preflight and atomic apply for Autographen 9.6 migration 1."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any

from backend.config import ROOT, get_settings
from backend.github.errors import RepositoryError, RepositoryNotFoundError
from backend.github.github_repository import GitHubDataRepository
from backend.github.repository import DataRepository, RepositoryFile
from backend.modules import get_module
from backend.records.generic_read import parse_record_file, record_path
from backend.records.generic_write import render_record_content
from backend.records.module_index import (
    IndexPlan,
    build_module_index,
    dump_index,
    index_path,
    read_module_index,
)
from backend.records.runtime import RecordRuntime

from .migration1 import (
    DEFAULT_OUTPUT_DIR,
    EXPECTED_SOURCE_SHA256,
    MODULE_KEY,
    MigrationError,
    expected_signatures,
    read_source_rows,
    transform_row,
    validate_record,
    validate_signature_selection,
    verify_source_hash,
)


EXPECTED_DATA_HEAD = "2f063cd6d0fb85e3e66b0fd75ca1e8ea9748fd5a"
CONFIRMATION = "APPLY-AUTOGRAPHEN-9-6-MIGRATION-1"
COMMIT_MESSAGE = "Importiere Autographen 9.6 Migration 1"
PREFLIGHT_SUCCESS = "PREFLIGHT ERFOLGREICH – APPLY NOCH NICHT AUSGEFÜHRT."
APPLY_SUCCESS = "MIGRATION 1 PRODUKTIV ERFOLGREICH ABGESCHLOSSEN."


class ApplySafetyError(MigrationError):
    """A failed invariant that must stop preflight or apply."""


class ReadOnlyRepositoryCache:
    """Per-run cache that structurally forbids writes during preflight planning."""

    def __init__(self, repository: DataRepository) -> None:
        self.repository = repository
        self.files: dict[str, RepositoryFile | None] = {}
        self.directories: dict[str, tuple[RepositoryFile, ...]] = {}

    def get_branch_head(self) -> str:
        return self.repository.get_branch_head()

    def read_file(self, path: str) -> RepositoryFile:
        if path not in self.files:
            try:
                self.files[path] = self.repository.read_file(path)
            except RepositoryNotFoundError:
                self.files[path] = None
        file = self.files[path]
        if file is None:
            raise RepositoryNotFoundError(path)
        return file

    def list_directory(self, path: str) -> list[RepositoryFile]:
        if path not in self.directories:
            self.directories[path] = tuple(self.repository.list_directory(path))
        return list(self.directories[path])

    def get_commit_parent(self, commit_sha: str) -> str:
        return self.repository.get_commit_parent(commit_sha)

    def commit_files(self, *, expected_head: str, files: dict[str, str], message: str) -> str:
        raise ApplySafetyError("Read-only Preflight darf commit_files() nicht aufrufen.")


@dataclass(frozen=True)
class ApplyConfiguration:
    expected_source_sha256: str = EXPECTED_SOURCE_SHA256
    expected_data_head: str = EXPECTED_DATA_HEAD
    required_signatures: tuple[str, ...] = expected_signatures()
    expected_record_count: int = 264


@dataclass(frozen=True)
class WritePlan:
    source_sha256: str
    expected_head: str
    records: tuple[dict[str, Any], ...]
    files: dict[str, str]
    index: dict[str, Any]
    fingerprint: str
    schema_errors: int
    vocabulary_errors: int
    warnings: tuple[dict[str, Any], ...]

    @property
    def record_paths(self) -> tuple[str, ...]:
        return tuple(sorted(path for path in self.files if path.startswith("data/autographen/")))


@dataclass(frozen=True)
class PreflightResult:
    plan: WritePlan
    report: dict[str, Any]
    state_content: str
    state_revision: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _code_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _plan_fingerprint(source_hash: str, expected_head: str, files: dict[str, str]) -> str:
    representation = {
        "source_sha256": source_hash,
        "expected_data_head": expected_head,
        "files": [{"path": path, "content": files[path]} for path in sorted(files)],
    }
    return sha256(_json_bytes(representation)).hexdigest()


def _read_json_file(path: Path, description: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ApplySafetyError(f"{description} fehlt oder ist ungueltig: {path}") from exc


def verify_qa_artifacts(artifacts_dir: Path) -> None:
    errors = _read_json_file(artifacts_dir / "errors.json", "Dry-Run-Fehlerbericht")
    if errors != []:
        raise ApplySafetyError("errors.json muss exakt eine leere Fehlerliste enthalten.")
    try:
        qa_report = (artifacts_dir / "qa_report.md").read_text(encoding="utf-8")
    except OSError as exc:
        raise ApplySafetyError("QA-Bericht fehlt.") from exc
    release = "MIGRATION 1 FACHLICH UND TECHNISCH ZUM APPLY FREIGEGEBEN."
    if release not in qa_report:
        raise ApplySafetyError("QA-Bericht enthält keine abgeschlossene Apply-Freigabe.")


def _validate_source_records(
    source: Path,
    repository: DataRepository,
    configuration: ApplyConfiguration,
) -> tuple[str, Any, tuple[dict[str, Any], ...], int, int, tuple[dict[str, Any], ...]]:
    module = get_module(MODULE_KEY)
    try:
        source_hash = verify_source_hash(source, configuration.expected_source_sha256)
        rows = read_source_rows(source)
        sorted_rows = validate_signature_selection(
            rows,
            required=configuration.required_signatures,
            bestand=module.signature_strategy["bestand"],
        )
    except MigrationError as exc:
        raise ApplySafetyError(str(exc)) from exc
    if len(rows) != configuration.expected_record_count or len(sorted_rows) != configuration.expected_record_count:
        raise ApplySafetyError(
            f"Migration erwartet {configuration.expected_record_count} Quellrecords, erhalten {len(rows)}."
        )
    runtime = RecordRuntime(module, repository)
    records: list[dict[str, Any]] = []
    schema_errors = 0
    vocabulary_errors = 0
    validation_messages: list[str] = []
    for position, row in enumerate(sorted_rows, start=1):
        try:
            record, _ = transform_row(row, position, module)
        except MigrationError as exc:
            raise ApplySafetyError(f"{row.signature}: {exc}") from exc
        record_errors = validate_record(record, runtime, row.signature, row.values)
        schema_errors += sum(error.get("error_type") == "schema" for error in record_errors)
        vocabulary_errors += sum(error.get("error_type") == "vocabulary" for error in record_errors)
        validation_messages.extend(error["message"] for error in record_errors)
        records.append(record)
    if validation_messages:
        raise ApplySafetyError("Zielrecord-Validierung fehlgeschlagen: " + "; ".join(validation_messages))
    ids = [record["id"] for record in records]
    signatures = [record["signatur"]["anzeige"] for record in records]
    expected_ids = [f"autograph-{position:06d}" for position in range(1, configuration.expected_record_count + 1)]
    if ids != expected_ids or len(set(ids)) != configuration.expected_record_count:
        raise ApplySafetyError("Technische IDs entsprechen nicht dem erwarteten lueckenlosen Bereich.")
    if signatures != list(configuration.required_signatures) or len(set(signatures)) != configuration.expected_record_count:
        raise ApplySafetyError("Zielsignaturen entsprechen nicht der erwarteten eindeutigen Reihenfolge.")
    if any(int(signature.split(".")[2].rstrip("ab")) >= 263 for signature in signatures):
        raise ApplySafetyError("Migration 1 enthält eine Signatur ab 9.6.263.")
    return source_hash, module, tuple(records), schema_errors, vocabulary_errors, ()


def _read_state(repository: DataRepository, module) -> tuple[dict[str, Any], RepositoryFile]:
    state_path = (module.storage.get("state") or {}).get("path")
    if not isinstance(state_path, str) or not state_path:
        raise ApplySafetyError("State-Pfad fehlt in der Modulkonfiguration.")
    state_file = repository.read_file(state_path)
    try:
        state = json.loads(state_file.content)
    except (ValueError, TypeError) as exc:
        raise ApplySafetyError("Produktiver Autographen-State ist kein gueltiges JSON.") from exc
    if not isinstance(state, dict):
        raise ApplySafetyError("Produktiver Autographen-State ist kein Objekt.")
    if state.get("next_record_id") != 265:
        raise ApplySafetyError(f"next_record_id ist {state.get('next_record_id')!r} statt 265.")
    signature_numbers = state.get("next_signature_number")
    if not isinstance(signature_numbers, dict) or signature_numbers.get("A") != 263:
        actual = signature_numbers.get("A") if isinstance(signature_numbers, dict) else None
        raise ApplySafetyError(f"next_signature_number['A'] ist {actual!r} statt 263.")
    if state.get("create_operations") != {}:
        raise ApplySafetyError("create_operations ist nicht leer.")
    return state, state_file


def _list_existing_records(repository: DataRepository, module) -> list[RepositoryFile]:
    try:
        files = repository.list_directory(module.storage["data_dir"])
    except RepositoryNotFoundError:
        return []
    extension = module.storage.get("filename", {}).get("extension", ".md")
    return [file for file in files if file.path.endswith(extension)]


def _assert_empty_repository_state(repository: DataRepository, module) -> tuple[dict[str, Any], RepositoryFile, dict[str, Any]]:
    existing = _list_existing_records(repository, module)
    if existing:
        raise ApplySafetyError(
            "Produktiver Autographenbestand ist nicht leer: " + ", ".join(file.path for file in existing)
        )
    state, state_file = _read_state(repository, module)
    try:
        current_index = read_module_index(repository, module)
    except RepositoryError as exc:
        raise ApplySafetyError("Produktiver Modulindex fehlt, ist veraltet oder ungueltig.") from exc
    if current_index["records"] != []:
        raise ApplySafetyError("Produktiver Modulindex ist nicht leer.")
    return state, state_file, current_index


def _build_write_plan(
    source_hash: str,
    expected_head: str,
    module,
    records: tuple[dict[str, Any], ...],
    repository: DataRepository,
    schema_errors: int,
    vocabulary_errors: int,
    warnings: tuple[dict[str, Any], ...],
    configuration: ApplyConfiguration,
) -> WritePlan:
    record_files = {
        record_path(module, record["id"]): render_record_content(record)
        for record in records
    }
    repository_files = [
        RepositoryFile(path=path, content=content, revision="planned")
        for path, content in sorted(record_files.items())
    ]
    planned_index = build_module_index(module, repository_files, repository)
    planned_index_content = dump_index(planned_index)
    target_index_path = index_path(module)
    if not target_index_path:
        raise ApplySafetyError("Modulindex-Pfad fehlt.")
    files = {**record_files, target_index_path: planned_index_content}
    expected_record_paths = {
        f"{module.storage['data_dir'].rstrip('/')}/autograph-{position:06d}.md"
        for position in range(1, configuration.expected_record_count + 1)
    }
    actual_record_paths = set(record_files)
    state_path = (module.storage.get("state") or {}).get("path")
    if actual_record_paths != expected_record_paths:
        raise ApplySafetyError("Geplante Recordpfade entsprechen nicht exakt der Migration-1-Zielmenge.")
    if set(files) != expected_record_paths | {target_index_path} or state_path in files:
        raise ApplySafetyError("Schreibplan enthält unerwartete Pfade oder den State.")
    if len(record_files) != configuration.expected_record_count or len(files) != configuration.expected_record_count + 1:
        raise ApplySafetyError("Schreibplan enthält nicht exakt Records plus einen Modulindex.")
    if len(planned_index.get("records") or []) != configuration.expected_record_count:
        raise ApplySafetyError("Geplanter Modulindex enthält nicht die erwartete Recordanzahl.")
    fingerprint = _plan_fingerprint(source_hash, expected_head, files)
    return WritePlan(
        source_sha256=source_hash,
        expected_head=expected_head,
        records=records,
        files=files,
        index=planned_index,
        fingerprint=fingerprint,
        schema_errors=schema_errors,
        vocabulary_errors=vocabulary_errors,
        warnings=warnings,
    )


def build_preflight(
    repository: DataRepository,
    source: Path,
    artifacts_dir: Path,
    *,
    configuration: ApplyConfiguration = ApplyConfiguration(),
    repository_name: str = "in-memory",
    branch: str = "main",
    code_commit: str | None = None,
) -> PreflightResult:
    source = source.resolve()
    artifacts_dir = artifacts_dir.resolve()
    read_repository = ReadOnlyRepositoryCache(repository)
    verify_qa_artifacts(artifacts_dir)
    source_hash, module, records, schema_errors, vocabulary_errors, warnings = _validate_source_records(
        source, read_repository, configuration,
    )
    checked_head = read_repository.get_branch_head()
    if checked_head != configuration.expected_data_head:
        raise ApplySafetyError(
            f"Datenbranch-Head ist {checked_head}, erwartet {configuration.expected_data_head}."
        )
    state, state_file, current_index = _assert_empty_repository_state(read_repository, module)
    plan = _build_write_plan(
        source_hash,
        checked_head,
        module,
        records,
        read_repository,
        schema_errors,
        vocabulary_errors,
        warnings,
        configuration,
    )
    final_head = read_repository.get_branch_head()
    if final_head != checked_head:
        raise ApplySafetyError(
            f"Datenbranch-Head hat sich waehrend des Preflights geaendert: {checked_head} -> {final_head}."
        )
    index_plan = IndexPlan(module)
    report = {
        "status": PREFLIGHT_SUCCESS,
        "timestamp": _utc_now(),
        "code_repository_commit": code_commit or _code_commit(),
        "source_filename": source.name,
        "source_sha256": source_hash,
        "data_repository": repository_name,
        "data_branch": branch,
        "checked_data_head": checked_head,
        "expected_data_head": configuration.expected_data_head,
        "state": state,
        "state_revision": state_file.revision,
        "index_schema_version": current_index["schema_version"],
        "index_module": current_index["module"],
        "index_configuration_fingerprint": index_plan.fingerprint,
        "existing_production_records": 0,
        "planned_records": len(records),
        "planned_record_files": len(plan.record_paths),
        "planned_index_files": 1,
        "planned_files_total": len(plan.files),
        "first_signature": records[0]["signatur"]["anzeige"],
        "last_signature": records[-1]["signatur"]["anzeige"],
        "first_record_id": records[0]["id"],
        "last_record_id": records[-1]["id"],
        "schema_errors": schema_errors,
        "vocabulary_errors": vocabulary_errors,
        "warnings": len(warnings),
        "warning_details": list(warnings),
        "plan_fingerprint_sha256": plan.fingerprint,
        "state_will_be_written": False,
        "planned_repository_commits": 1,
        "commit_message": COMMIT_MESSAGE,
    }
    return PreflightResult(
        plan=plan,
        report=report,
        state_content=state_file.content,
        state_revision=state_file.revision,
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_preflight_reports(result: PreflightResult, artifacts_dir: Path) -> tuple[Path, Path]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    json_path = artifacts_dir / "apply_preflight.json"
    markdown_path = artifacts_dir / "apply_preflight.md"
    _write_json(json_path, result.report)
    report = result.report
    markdown = f"""# Apply-Preflight – Autographen 9.6 Migration 1

- Zeitpunkt: `{report['timestamp']}`
- Code-Commit: `{report['code_repository_commit']}`
- Quelle: `{report['source_filename']}`
- Source-SHA-256: `{report['source_sha256']}`
- Datenrepository: `{report['data_repository']}`
- Datenbranch: `{report['data_branch']}`
- Erwarteter Head: `{report['expected_data_head']}`
- Geprüfter Head: `{report['checked_data_head']}`
- State: `next_record_id={report['state']['next_record_id']}`, `next_signature_number.A={report['state']['next_signature_number']['A']}`, `create_operations={{}}`
- Index-Fingerprint: `{report['index_configuration_fingerprint']}`
- Vorhandene Produktivrecords: {report['existing_production_records']}
- Geplante Records: {report['planned_records']}
- Geplante Dateien: {report['planned_files_total']} ({report['planned_record_files']} Records + 1 Index)
- Signaturen: `{report['first_signature']}` bis `{report['last_signature']}`
- IDs: `{report['first_record_id']}` bis `{report['last_record_id']}`
- Schemafehler: {report['schema_errors']}
- Vokabularfehler: {report['vocabulary_errors']}
- Warnungen: {report['warnings']}
- Plan-Fingerprint: `{report['plan_fingerprint_sha256']}`
- State wird geschrieben: nein
- Geplante Repository-Commits: 1

`{report['status']}`
"""
    markdown_path.write_text(markdown, encoding="utf-8")
    return json_path, markdown_path


def _load_approved_preflight(artifacts_dir: Path) -> dict[str, Any]:
    report = _read_json_file(artifacts_dir / "apply_preflight.json", "Apply-Preflight-Bericht")
    if not isinstance(report, dict) or report.get("status") != PREFLIGHT_SUCCESS:
        raise ApplySafetyError("Apply-Preflight-Bericht ist nicht erfolgreich freigegeben.")
    fingerprint = report.get("plan_fingerprint_sha256")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ApplySafetyError("Apply-Preflight enthält keinen gueltigen Plan-Fingerprint.")
    return report


def _verify_after_apply(
    repository: DataRepository,
    result: PreflightResult,
    new_head: str,
    configuration: ApplyConfiguration,
) -> dict[str, Any]:
    module = get_module(MODULE_KEY)
    if new_head == result.plan.expected_head:
        raise ApplySafetyError("Apply hat keinen neuen Datenbranch-Head erzeugt.")
    if repository.get_branch_head() != new_head:
        raise ApplySafetyError("Apply-Commit ist nicht der aktuelle Datenbranch-Head.")
    if repository.get_commit_parent(new_head) != result.plan.expected_head:
        raise ApplySafetyError("Parent des Apply-Commits ist nicht der geprüfte Ausgangs-Head.")
    stored_files = _list_existing_records(repository, module)
    expected_paths = set(result.plan.record_paths)
    if {file.path for file in stored_files} != expected_paths:
        raise ApplySafetyError("Post-Apply-Recordpfade weichen vom Schreibplan ab.")
    runtime = RecordRuntime(module, repository)
    ids: list[str] = []
    signatures: list[str] = []
    for file in sorted(stored_files, key=lambda item: item.path):
        if file.content != result.plan.files[file.path]:
            raise ApplySafetyError(f"Post-Apply-Inhalt weicht vom Schreibplan ab: {file.path}")
        stored = parse_record_file(file)
        runtime.validate(stored.data)
        runtime.validate_vocabulary_references(stored.data)
        ids.append(stored.record_id)
        signatures.append(stored.data["signatur"]["anzeige"])
    expected_ids = [f"autograph-{position:06d}" for position in range(1, configuration.expected_record_count + 1)]
    if ids != expected_ids or set(signatures) != set(configuration.required_signatures):
        raise ApplySafetyError("Post-Apply-IDs oder Signaturen weichen ab.")
    stored_index_file = repository.read_file(index_path(module))
    if stored_index_file.content != result.plan.files[index_path(module)]:
        raise ApplySafetyError("Post-Apply-Modulindex weicht byteweise vom Schreibplan ab.")
    stored_index = read_module_index(repository, module)
    if len(stored_index["records"]) != configuration.expected_record_count:
        raise ApplySafetyError("Post-Apply-Modulindex enthält die falsche Recordanzahl.")
    if {entry["record_id"] for entry in stored_index["records"]} != set(expected_ids):
        raise ApplySafetyError("Post-Apply-Index-IDs weichen von den Recorddateien ab.")
    state, state_file = _read_state(repository, module)
    if state_file.content != result.state_content or state_file.revision != result.state_revision:
        raise ApplySafetyError("State wurde durch den Apply verändert.")
    return {
        "new_head": new_head,
        "records": len(stored_files),
        "index_records": len(stored_index["records"]),
        "schema_errors": 0,
        "vocabulary_errors": 0,
        "state": state,
        "record_index_consistent": True,
        "content_matches_plan": True,
    }


def _write_apply_reports(
    artifacts_dir: Path,
    result: PreflightResult,
    new_head: str,
    verification: dict[str, Any] | None,
    error: str | None,
) -> None:
    status = APPLY_SUCCESS if error is None else "POST-APPLY-VERIFIKATION FEHLGESCHLAGEN – KEINE WEITEREN SCHREIBOPERATIONEN."
    payload = {
        "status": status,
        "timestamp": _utc_now(),
        "source_sha256": result.plan.source_sha256,
        "plan_fingerprint_sha256": result.plan.fingerprint,
        "old_data_head": result.plan.expected_head,
        "new_data_head": new_head,
        "commit_hash": new_head,
        "commit_message": COMMIT_MESSAGE,
        "written_record_files": len(result.plan.record_paths),
        "index_records": verification.get("index_records") if verification else None,
        "schema_errors": verification.get("schema_errors") if verification else None,
        "vocabulary_errors": verification.get("vocabulary_errors") if verification else None,
        "state_before": json.loads(result.state_content),
        "state_after": verification.get("state") if verification else None,
        "record_index_consistent": verification.get("record_index_consistent") if verification else False,
        "content_matches_plan": verification.get("content_matches_plan") if verification else False,
        "deviations": [error] if error else [],
    }
    _write_json(artifacts_dir / "apply_report.json", payload)
    markdown = "# Apply-Bericht – Autographen 9.6 Migration 1\n\n"
    markdown += f"- Alter Head: `{result.plan.expected_head}`\n- Neuer Head: `{new_head}`\n"
    markdown += f"- Plan-Fingerprint: `{result.plan.fingerprint}`\n- Geschriebene Records: {len(result.plan.record_paths)}\n"
    if error:
        markdown += f"- Abweichung: {error}\n\n`{status}`\n"
    else:
        markdown += f"- Indexeinträge: {verification['index_records']}\n- State unverändert: ja\n\n`{status}`\n"
    (artifacts_dir / "apply_report.md").write_text(markdown, encoding="utf-8")


def perform_apply(
    repository: DataRepository,
    source: Path,
    artifacts_dir: Path,
    confirmation: str | None,
    *,
    configuration: ApplyConfiguration = ApplyConfiguration(),
    repository_name: str = "in-memory",
    branch: str = "main",
    code_commit: str | None = None,
) -> dict[str, Any]:
    if confirmation != CONFIRMATION:
        raise ApplySafetyError(f"Apply erfordert --confirm {CONFIRMATION}.")
    approved = _load_approved_preflight(artifacts_dir)
    current_code_commit = code_commit or _code_commit()
    if approved.get("expected_data_head") != configuration.expected_data_head:
        raise ApplySafetyError("Freigegebener Preflight gilt nicht fuer den erwarteten Datenbranch-Head.")
    if approved.get("code_repository_commit") != current_code_commit:
        raise ApplySafetyError("Code-Commit stimmt nicht mit dem freigegebenen Preflight überein.")
    if approved.get("data_repository") != repository_name or approved.get("data_branch") != branch:
        raise ApplySafetyError("Datenrepository oder Branch stimmt nicht mit dem freigegebenen Preflight überein.")
    if approved.get("source_sha256") != configuration.expected_source_sha256:
        raise ApplySafetyError("Source-SHA stimmt nicht mit dem freigegebenen Preflight überein.")
    result = build_preflight(
        repository,
        source,
        artifacts_dir,
        configuration=configuration,
        repository_name=repository_name,
        branch=branch,
        code_commit=current_code_commit,
    )
    if approved.get("plan_fingerprint_sha256") != result.plan.fingerprint:
        raise ApplySafetyError("Neu berechneter Schreibplan stimmt nicht mit dem freigegebenen Preflight überein.")
    if approved.get("checked_data_head") != result.plan.expected_head:
        raise ApplySafetyError("Datenbranch-Head stimmt nicht mit dem freigegebenen Preflight überein.")
    new_head = repository.commit_files(
        expected_head=result.plan.expected_head,
        files=result.plan.files,
        message=COMMIT_MESSAGE,
    )
    try:
        verification = _verify_after_apply(repository, result, new_head, configuration)
    except Exception as exc:
        _write_apply_reports(artifacts_dir, result, new_head, None, str(exc))
        raise
    _write_apply_reports(artifacts_dir, result, new_head, verification, None)
    return verification


def _repository_details(repository: GitHubDataRepository) -> tuple[str, str]:
    settings = repository.settings
    return f"{settings.github_data_owner}/{settings.github_data_repo}", settings.github_data_branch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gesicherter Apply fuer Autographen 9.6 Migration 1")
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("preflight", "apply"):
        command = subparsers.add_parser(action)
        command.add_argument("--source", required=True, type=Path)
        command.add_argument("--artifacts-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
        if action == "apply":
            command.add_argument("--confirm")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    repository = GitHubDataRepository(settings)
    repository_name, branch = _repository_details(repository)
    try:
        if args.action == "preflight":
            result = build_preflight(
                repository,
                args.source,
                args.artifacts_dir,
                repository_name=repository_name,
                branch=branch,
            )
            json_path, markdown_path = write_preflight_reports(result, args.artifacts_dir)
            print(f"Source-SHA-256: {result.plan.source_sha256}")
            print(f"Datenbranch-Head: {result.plan.expected_head}")
            print(f"Vorhandene Autographenrecords: {result.report['existing_production_records']}")
            print(f"Geplante Records: {result.report['planned_records']}")
            print(f"Geplante Dateien: {result.report['planned_files_total']}")
            print(f"Plan-Fingerprint: {result.plan.fingerprint}")
            print(f"JSON-Bericht: {json_path}")
            print(f"Markdown-Bericht: {markdown_path}")
            print(PREFLIGHT_SUCCESS)
            return 0
        verification = perform_apply(
            repository,
            args.source,
            args.artifacts_dir,
            args.confirm,
            repository_name=repository_name,
            branch=branch,
        )
        print(f"Neuer Datenbranch-Head: {verification['new_head']}")
        print(APPLY_SUCCESS)
        return 0
    except (ApplySafetyError, RepositoryError, OSError) as exc:
        print(f"{args.action.upper()} ABGEBROCHEN: {exc}")
        print("ES WURDEN KEINE WEITEREN PRODUKTDATEN VERAENDERT.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
