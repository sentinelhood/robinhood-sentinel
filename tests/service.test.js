import {test} from 'node:test';
import assert from 'node:assert/strict';
import handler, {validate} from '../api/service.js';
test('valid address/hash and Aeon query accepted',()=>{validate('address','0x'+'1'.repeat(40));validate('transaction','0x'+'a'.repeat(64));validate('aeon','onchain monitor');validate('network');});
test('invalid, arbitrary and write actions rejected',()=>{for(const [a,v] of [['address','0x123'],['transaction','hello'],['eth_sendRawTransaction','0x123'],['aeon',''],['aeon','a'.repeat(201)],['address',['0x'+'1'.repeat(40),'evil']]]) assert.throws(()=>validate(a,v));});
test('POST is refused before any RPC call',async()=>{let status;const res={setHeader(){},status(n){status=n;return this},json(){}};await handler({method:'POST'},res);assert.equal(status,405);});