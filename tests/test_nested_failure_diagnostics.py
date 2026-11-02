import copy,json,os,tempfile,unittest
from pathlib import Path
from receive_diagnostics import record_failure,valid_failure,diagnostic_result,valid_cleanup
from receiver_result_receipt import write_receipt
from receiver_result_reader import read_receipt
from test_receive_diagnostics import details

class NestedFailureTests(unittest.TestCase):
 def receipt(self,result):
  with tempfile.TemporaryDirectory() as t:
   directory=Path(t);directory.chmod(0o770);run='d'*32
   result={**result,'run':run,'featureExclusivity':'cooperative-only-unproven'}
   info=lambda:{'pid':os.getpid(),'startTicks':1,'status':{'Uid':' '.join([str(os.getuid())]*4),'Gid':'5000 5000 5000 5000','Groups':'5000','CapEff':'0000000000000000'}}
   write_receipt(directory,run,result,state_uid=os.getuid(),group=os.getgid(),process_info=info)
   path=directory/('receiver-result-'+run+'.json');self.assertLess(path.stat().st_size,4096)
   return read_receipt(directory,run,state_uid=os.getuid(),group=os.getgid())
 def inner(self):
  d=details();d['reportShapes']=[{'id':252,'length':i+1,'count':100000000} for i in range(12)]
  stats={};record_failure(stats,'feed',RuntimeError('managed system key already held'));d['receiveFailure']=stats['receiveFailure']
  return {'status':'attention','phase':'receive','sensorStopVerified':True,'diagnostic':'other-RuntimeError','errorType':'RuntimeError','readStats':{'receiveDiagnostics':d},'outputCounts':dict.fromkeys(('keyFrameWrites','clickFrameWrites','motionFrameWrites'),12)}
 def test_cleanup_keeps_original_failure_without_promoting_stop_proof(self):
  result={'status':'attention','reason':'app-cleanup-unverified','errors':['status-pump-stop-error','private secret'], 'sessionResult':{'status':'attention','reason':'resource-close-unverified','errors':['system-key-release-unverified'],'sessionResult':self.inner()}}
  r=self.receipt(result)
  self.assertEqual(r['status'],'attention');self.assertFalse(r['sensorStopVerified']);self.assertFalse(r['journalArchived']);self.assertIsNone(r['counts'])
  self.assertEqual(r['diagnostic'],'other-RuntimeError');self.assertEqual(r['phase'],'receive');self.assertEqual(r['frameCounts']['keyFrameWrites'],12)
  self.assertEqual(r['receiveDiagnostics']['receiveFailure']['code'],'system-key-held')
  self.assertEqual(r['cleanupDiagnostics'],[{'stage':'app-cleanup-unverified','errors':['status-pump-stop-error']},{'stage':'resource-close-unverified','errors':['system-key-release-unverified']}])
  self.assertNotIn('private',json.dumps(r))
 def test_unknown_wrapper_is_not_traversed(self):
  result={'status':'attention','reason':'unknown','sessionResult':self.inner()}
  source,cleanup=diagnostic_result(result);self.assertIs(source,result);self.assertEqual(cleanup,[])
  r=self.receipt(result);self.assertNotIn('receiveDiagnostics',r);self.assertNotIn('cleanupDiagnostics',r)
 def test_diagnostic_code_is_bounded_and_legacy_failure_is_accepted(self):
  stats={};record_failure(stats,'feed',RuntimeError('private secret'));self.assertIsNone(stats['receiveFailure']['code']);self.assertNotIn('private',json.dumps(stats))
  record_failure(stats,'tick',RuntimeError('managed system key already held'));self.assertEqual(stats['receiveFailure']['stage'],'feed')
  self.assertTrue(valid_failure({'stage':'feed','type':'RuntimeError','errno':None}))
  self.assertFalse(valid_failure({'stage':'feed','type':'RuntimeError','errno':None,'code':'private secret'}))
 def test_cleanup_schema_rejects_unknown_or_duplicate_data(self):
  good=[{'stage':'resource-close-unverified','errors':['system-key-release-unverified']}]
  self.assertTrue(valid_cleanup(good))
  for bad in ([{**good[0],'raw':'secret'}],[{**good[0],'errors':['private']}],[{**good[0],'errors':good[0]['errors']*2}],good*3):self.assertFalse(valid_cleanup(bad))
