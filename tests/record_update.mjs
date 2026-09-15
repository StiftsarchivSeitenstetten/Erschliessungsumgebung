import assert from 'node:assert/strict';
import {RecordUpdate,sendQueuedRecordUpdate} from '../app/generic/record-update.js';
import {FormState} from '../app/generic/form-state.js';
const descriptor = {fields:[{path:'text',visible:true,editable:true},{path:'id',visible:true,editable:false},{path:'hidden',visible:false,editable:false}]};
function fixture(request) {
  const form = new FormState(descriptor,{id:'existing',text:'original',hidden:'protected'});
  return new RecordUpdate('other-module','existing',form,'revision-a',request);
}
const response = {record_id:'existing',record:{text:'changed',id:'existing'},meta:{revision:'revision-b'}};
let calls = [];
const updater = fixture(async (url,options)=>{calls.push({url,options});return {ok:true,json:async()=>response};});
assert.equal(updater.canSave('edit'),false);
updater.formState.setValue('text','changed');
assert.equal(updater.canSave('read'),false);
assert.equal(updater.canSave('edit'),true);
await updater.save('edit','csrf-test');
assert.equal(calls[0].url,'/api/modules/other-module/records/existing');
assert.equal(calls[0].options.method,'PUT');
assert.equal(calls[0].options.headers['X-CSRF-Token'],'csrf-test');
assert.deepEqual(JSON.parse(calls[0].options.body),{base_revision:'revision-a',record:{text:'changed'}});
assert.deepEqual(updater.formState.original,response.record);
assert.deepEqual(updater.formState.serverSnapshot,response.record);
assert.deepEqual(updater.formState.workingRecord,response.record);
assert.equal(updater.formState.pendingSnapshot,null);
assert.equal(updater.formState.isDirty(),false);
assert.equal(updater.revision,'revision-b');
updater.formState.setValue('text','changed again');
assert.equal(updater.formState.isDirty(),true);
response.record.text = 'changed again';
response.meta.revision = 'revision-c';
await updater.save('edit','csrf');
assert.deepEqual(JSON.parse(calls[1].options.body),{base_revision:'revision-b',record:{text:'changed again'}});
assert.equal(updater.revision,'revision-c');
assert.equal(updater.formState.isDirty(),false);
assert.equal(calls.length,2);

const structured = fixture(async()=>{throw new Error('not called');});
structured.formState.setValue('text','original');
structured.formState.workingRecord.technik = {geaendert_von:'server'};
assert.equal(structured.formState.isDirty(),false);
structured.formState.setValue('text',{b:2,a:1});
structured.formState.serverSnapshot.text = {a:1,b:2};
assert.equal(structured.formState.isDirty(),false);
for (const status of [401,403,409,422,500]) {
  const u = fixture(async()=>({ok:false,status,json:async()=>({detail:['invalid']})}));
  u.formState.setValue('text','keep me');
  await assert.rejects(()=>u.save('edit','csrf'));
  assert.equal(u.formState.getValue('text'),'keep me');
  assert.equal(u.formState.isDirty(),true);
  assert.equal(u.formState.pendingSnapshot,null);
  assert.equal(u.revision,'revision-a');
  assert.equal(u.canSave('edit'),true);
}
const network = fixture(async()=>{throw new Error('network');});
network.formState.setValue('text','keep me');
await assert.rejects(()=>network.save('edit','csrf'));
assert.equal(network.formState.isDirty(),true);
assert.equal(network.canSave('edit'),true);
let finish;
let count=0;
const delayed = fixture(()=>{count++;return new Promise(resolve=>{finish=resolve;});});
delayed.formState.setValue('text','changed');
const first = delayed.save('edit','csrf');
assert.deepEqual(delayed.formState.pendingSnapshot,{id:'existing',text:'changed',hidden:'protected'});
delayed.formState.setValue('text','newer change');
assert.equal(delayed.canSave('edit'),false);
assert.equal(await delayed.save('edit','csrf'),null);
assert.equal(count,1);
finish({ok:true,json:async()=>({record_id:'existing',record:{id:'existing',text:'changed'},meta:{revision:'revision-b'}})});
await first;
assert.equal(delayed.formState.getValue('text'),'newer change');
assert.equal(delayed.formState.serverSnapshot.text,'changed');
assert.equal(delayed.formState.pendingSnapshot,null);
assert.equal(delayed.formState.isDirty(),true);
assert.equal(delayed.canSave('edit'),true);
let secondBody;
delayed.request = async(url,options)=>{
  secondBody = JSON.parse(options.body);
  return {ok:true,json:async()=>({record_id:'existing',record:{id:'existing',text:'newer change'},meta:{revision:'revision-c'}})};
};
await delayed.save('edit','csrf');
assert.deepEqual(secondBody,{base_revision:'revision-b',record:{text:'newer change'}});
assert.equal(delayed.formState.isDirty(),false);
assert.equal(delayed.revision,'revision-c');
console.log('PUT cycles, snapshots, revisions, concurrent edits, errors and duplicate-save assertions passed');
const originalFetch = globalThis.fetch;
globalThis.fetch = function () {
  assert.notEqual(this, defaultUpdate);
  return Promise.resolve({ok:true,json:async()=>response});
};
const defaultUpdate = fixture(undefined);
defaultUpdate.formState.setValue('text','changed');
await defaultUpdate.save('edit','csrf');
assert.equal(defaultUpdate.formState.isDirty(),false);
globalThis.fetch = originalFetch;

let queuedCall;
const queuedResponse = {module:'other-module',record_id:'existing',record:{id:'existing',text:'queued'},meta:{revision:'revision-q'}};
const queuedResult = await sendQueuedRecordUpdate({
  module_id:'other-module',record_id:'existing',base_revision:'revision-p',snapshot:{text:'queued'}
},'csrf-queue',async(url,options)=>{queuedCall={url,options};return {ok:true,json:async()=>queuedResponse};});
assert.equal(queuedCall.url,'/api/modules/other-module/records/existing');
assert.deepEqual(JSON.parse(queuedCall.options.body),{base_revision:'revision-p',record:{text:'queued'}});
assert.equal(queuedCall.options.headers['X-CSRF-Token'],'csrf-queue');
assert.equal(queuedResult.meta.revision,'revision-q');
