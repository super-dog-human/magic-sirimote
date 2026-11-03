'use strict';
// Read-only package inspection. Activation is added only with lifecycle support.
const Service = require('webos-service');
const childProcess = require('child_process');
const path = require('path');
const service = new Service('org.magicsirimote.app.service');
service.register('status', message => {
  childProcess.execFile('/usr/bin/python3', ['-I', '-B', path.join(__dirname, 'bundle_inspect.py')],
    {timeout: 10000, maxBuffer: 8192}, (error, stdout) => {
      if (error) { message.respond({returnValue: false, status: 'inspection-unavailable'}); return; }
      try { message.respond({returnValue: true, ...JSON.parse(stdout)}); }
      catch (_) { message.respond({returnValue: false, status: 'inspection-invalid'}); }
    });
});
