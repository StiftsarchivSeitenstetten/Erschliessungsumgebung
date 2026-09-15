import assert from "node:assert/strict";
import { ResultState, listColumns, listValue, renderRecordList } from "../app/generic/record-list.js";
import { createDefaultWidgetRegistry } from "../app/generic/widget-registry.js";
import { FormState } from "../app/generic/form-state.js";

const state = new ResultState("alternative", {path:"fields.code", direction:"desc"});
const rows = ["z", "a", "m"].map(record_id => ({record_id}));
state.replace(rows, {q:"", lookupField:"", lookupValue:""});
assert.equal(state.neighbor(1), null);
state.recordId = "z";
assert.equal(state.neighbor(-1), null);
assert.equal(state.neighbor(1), "a");
state.recordId = "a";
assert.equal(state.neighbor(-1), "z");
assert.equal(state.neighbor(1), "m");
state.recordId = "m";
assert.equal(state.neighbor(1), null);
assert.deepEqual(state.records, rows);
state.replace([rows[1]], {q:"Term", lookupField:"fields.code", lookupValue:"X.2"});
assert.equal(state.recordId, null);
state.recordId = "a";
assert.equal(state.neighbor(1), null);
assert.equal(state.neighbor(-1), null);
assert.match(state.url(), /q=Term/);
assert.match(state.url(), /lookup_field=fields.code/);
assert.match(state.url(), /record=a/);
state.lastRecordId = state.recordId;
state.recordId = null;
assert.equal(state.lastRecordId, "a");
assert.equal(state.q, "Term");
assert.equal(state.records.length, 1);
state.replace([], {q:"missing", lookupField:"", lookupValue:""});
assert.equal(state.neighbor(1), null);
assert.equal(state.records.length, 0);
state.replace(rows, {q:"", lookupField:"", lookupValue:""});
assert.equal(state.queryString(), "");
const descriptor = {fields:[{path:"x",label:"X"}],list:{columns:[{path:"y",label:"Y"},{path:"x"}]}};
assert.deepEqual(listColumns(descriptor).map(c=>c.label), ["Y","X"]);
assert.equal(listValue(null), "");
assert.equal(listValue({value:"X.2"}), "X.2");
assert.equal(listValue({year:1900,month:2}), "1900-2");
assert.equal(listValue({from:{year:1900},to:{year:1901}}), "1900 bis 1901");
console.log("Navigation state assertions passed");

const registry = createDefaultWidgetRegistry();
function dateRoot(parts) {
  return {querySelector: selector => ({value:parts[selector.match(/='([^']+)'/)[1]] || ""})};
}
const original = {from:{year:1900},to:{year:1901},display:"1900-1901"};
const fields = {from:"1900", to:"1901", note:""};
const context = {field:{},originalValue:original};
assert.deepEqual(registry.readValue('date_range',context,dateRoot(fields)),original);
const form = new FormState({fields:[{path:'range',visible:true,editable:true}]},{range:original});
form.setValue('range',registry.readValue('date_range',context,dateRoot({...fields,from:'1902'})));
assert.equal(form.isDirty(),true);
form.discardChanges();
form.setValue('range',registry.readValue('date_range',context,dateRoot(fields)));
assert.equal(form.isDirty(),false);
assert.equal(registry.readValue('date',{field:{},originalValue:null},dateRoot({})),null);
assert.deepEqual(registry.readValue('date',{field:{},originalValue:{year:1900,display:'old'}},dateRoot({'date.year':'1900'})),{year:1900,display:null});
console.log('Sparse date and discard roundtrip assertions passed');

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.events = {}; }
  append(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  addEventListener(name, callback) { this.events[name] = callback; }
  child(tag) { const element = new Element(tag); this.append(element); return element; }
  createTHead() { return this.child('thead'); }
  createTBody() { return this.child('tbody'); }
  insertRow() { return this.child('tr'); }
  insertCell() { return this.child('td'); }
}
globalThis.document = {createElement: tag => new Element(tag)};
const container = new Element('div');
let opened = null;
renderRecordList(container, {...descriptor,module:'other'}, [{record_id:'other-2',values:{x:'second',y:'first',hidden:'secret'}}], id=>{opened=id;});
const table = container.children[0];
assert.deepEqual(table.children[0].children[0].children.map(cell=>cell.textContent), ['Y','X']);
const cells = table.children[1].children[0].children;
assert.equal(cells.length,2);
assert.equal(cells[0].children[0].textContent,'first');
assert.equal(cells[1].textContent,'second');
cells[0].children[0].events.click({preventDefault(){}});
assert.equal(opened,'other-2');
assert.ok(cells[0].children[0].href.includes('record=other-2'));
renderRecordList(container,descriptor,[],()=>{});
assert.equal(container.textContent,'Keine Treffer.');
console.log('Configured table rendering and record opening assertions passed');
