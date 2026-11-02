'use strict';
// Public builds opt out of credential access/network renewal unless configured.
const POLICY='disabled';
async function run(options={}) {
 if(POLICY==='disabled')return {status:'maintenance-disabled'};
 return require('./expiry').run({...options,allowExtension:POLICY==='extend'&&options.allowExtension!==false});
}
module.exports={run};
