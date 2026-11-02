'use strict';
// Target bootstrap-node.js uses require(service_dir), not a CLI main invocation.
// Keep service.js import inert for tests; this explicit package entry starts once.
module.exports=require('./service').createService();
