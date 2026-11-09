import assert from 'node:assert/strict';
import {createSaveQueueProcessor} from '../app/generic/module-save-queue.js';
import {FormState} from '../app/generic/form-state.js';
import {classifyQueuedUpdateReadBack} from '../app/generic/record-update.js';
import {validateActionSnapshot} from '../app/generic/record-actions.js';
const clone=x=>structuredClone(x);
class Store {
  data=new Map();
  async list(){return [...this.data.values()].map(clone);}
  async get(id){return clone(this.data.get(id));}
  async put(x){this.data.set(x.operation_id,clone(x));return clone(x);}
  async update(id,x){return this.put({...await this.get(id),...x});}
  async remove(id){this.data.delete(id);}
}
const descriptor={create:{workflow:{status_path:'status',draft_status:'draft',completed_status:'complete'}},fields:[{path:'text',visible:true,editable:true},{path:'status',visible:true,editable:false}]};
const state=new FormState(descriptor,{text:'before',status:'draft'});
state.setValue('text','submitted');
const snapshot=state.beginSave();
state.setValue('text','edited while saving');
const store=new Store();
let calls=0;let remote;
const handler=async entry=>{
  calls++;
  assert.equal(entry.action,'complete');
  remote ||= {record_id:'id',record:{...entry.snapshot,status:'complete'},meta:{revision:'v2'}};
  if(calls===1)throw new Error('lost response');
  return remote;
};
let worker=createSaveQueueProcessor({store,sendCreate:handler});
await worker.enqueueCreate({operationId:'op',moduleId:'module',identityAssignment:'on_create',snapshot,action:'complete'});
await assert.rejects(()=>worker.enqueueCreate({operationId:'op',moduleId:'module',identityAssignment:'on_create',snapshot,action:'complete'}));
await worker.process();
assert.equal((await store.get('op')).action,'complete');
worker=createSaveQueueProcessor({store,sendCreate:handler,onSuccess:async (_entry,data)=>state.confirmSave(data.record)});
await worker.initializeRecovery();await worker.retryFirst();
assert.equal(state.current.text,'edited while saving');assert.equal(state.original.status,'complete');
assert.equal((await store.list()).length,0);
const entry={snapshot:{text:'submitted'},action:'complete',base_revision:'v1'};
assert.equal(classifyQueuedUpdateReadBack(entry,{record:{text:'submitted',status:'draft'},meta:{revision:'v1'}},descriptor).outcome,'not_applied');
assert.equal(classifyQueuedUpdateReadBack(entry,remote,descriptor).outcome,'applied');
const failedStore=new Store();
await assert.rejects(()=>validateActionSnapshot('module',{},'csrf',async()=>({ok:false,json:async()=>({detail:['Beschreibung: fehlt']})})));
assert.equal((await failedStore.list()).length,0);
console.log('Action snapshot, failed validation, duplicate create, lost response, reload, status readback and concurrent edit tests passed');
