import assert from 'node:assert/strict';
import {nextRecordSeed,singleFlight} from '../app/generic/next-record.js';
import {queueEntryMatchesContext} from '../app/generic/module-save-queue.js';
const descriptor={create:{next_record:{carry_fields:['kind','group']}},empty_record:{collection:'Fixed',kind:'default',group:'A',status:'draft',text:'',measures:[{kind:'Object',height:null,width:null,unit:'mm',note:''}]}};
const old={id:'old-id',collection:'Fixed',kind:'selected',group:'B',status:'complete',text:'Old',measures:[{kind:'Other',height:100}],technical:{author:'old'}};
const seed=nextRecordSeed(descriptor,old);
assert.equal(seed.kind,'selected');assert.equal(seed.group,'B');assert.equal(seed.status,'draft');assert.equal(seed.text,'');assert.equal(seed.id,undefined);assert.equal(seed.technical,undefined);
assert.deepEqual(seed.measures,descriptor.empty_record.measures);
seed.measures[0].unit='changed';assert.equal(descriptor.empty_record.measures[0].unit,'mm');
let release;let calls=0;
const action=singleFlight(async()=>{calls++;await new Promise(resolve=>release=resolve);return true;});
const first=action();assert.equal(await action(),false);assert.equal(calls,1);release();assert.equal(await first,true);
const oldState={}, newState={};
const context={operationId:'old-op',formState:oldState,create:{}};
assert.equal(queueEntryMatchesContext({operation_id:'old-op',module_id:'module',operation:'create'},context,{moduleId:'module',formState:newState,create:{},creating:true,recordId:null}),false);
console.log('Next-object defaults, whitelist, isolation, double-click and stale acknowledgement passed');

// Reservation and local promotion remain independent of an in-flight transfer.
const {createSaveQueueProcessor} = await import('../app/generic/module-save-queue.js');
const clone = value => structuredClone(value);
class Store {
  data=new Map();
  async list(){return [...this.data.values()].map(clone);}
  async get(id){return clone(this.data.get(id)||null);}
  async put(entry){this.data.set(entry.operation_id,clone(entry));return clone(entry);}
  async update(id,changes){return this.put({...await this.get(id),...changes});}
  async remove(id){this.data.delete(id);}
}
let globalLocked=false, releaseWrite, enteredWrite;
const entered=new Promise(resolve=>enteredWrite=resolve);
const lockManager={async request(name,options,callback){
  if(typeof options==='function')callback=options;
  if(name==='erschliessung-save-queue'){
    assert.equal(globalLocked,false,'reservation must not wait for the transfer lock');
    globalLocked=true;try{return await callback({});}finally{globalLocked=false;}
  }
  return callback({});
}};
const store=new Store();
const worker=createSaveQueueProcessor({store,lockManager,
  sendUpdate:async()=>{enteredWrite();await new Promise(resolve=>releaseWrite=resolve);return {meta:{revision:'new'}};},
  reserveIdentity:async entry=>({record_id:'new-object',identity:{id:'new-object'}}),
  sendCreate:async()=>({meta:{revision:'created'}})
});
await worker.enqueueUpdate({operationId:'old',moduleId:'module',recordId:'old-record',baseRevision:'old',snapshot:{text:'saved locally'}});
const processing=worker.process();await entered;
const reservation=await worker.prepareReservation({operationId:'new',moduleId:'module',identityInputs:{}});
assert.equal(reservation.operation,'reservation');
await worker.resumeReservation('new');
await worker.enqueueCreate({operationId:'new',moduleId:'module',identityAssignment:'reserve_before_create',requireReservation:true,snapshot:{text:'new object'}});
assert.equal((await store.get('old')).status,'saving');
assert.equal((await store.get('new')).status,'queued');
releaseWrite();await processing;
console.log('Next-object reservation and durable create are independent of an active transfer');

const {guardUnsavedChanges} = await import('../app/generic/next-record.js');
for (const choice of ['cancel', 'discard', 'save']) {
  for (const success of [false, true]) {
    let dirty = true, saves = 0;
    const allowed = await guardUnsavedChanges({hasChanges: () => dirty,
      choose: async () => choice, save: async () => {saves++; if (success) dirty = false; return success;}});
    assert.equal(allowed, choice === 'discard' || choice === 'save' && success);
    assert.equal(saves, choice === 'save' ? 1 : 0);
  }
}
assert.equal(await guardUnsavedChanges({hasChanges: () => false, choose: () => {throw Error('must not prompt');}}), true);
assert.equal(await guardUnsavedChanges({hasChanges: () => true, choose: async () => 'save', save: async () => true}), false, 'changes after a secured snapshot prevent the switch');
assert.deepEqual(nextRecordSeed(descriptor, {}), descriptor.empty_record);
console.log('Common navigation guard: cancel, discard, durable save, validation/local failure and intervening changes passed');
