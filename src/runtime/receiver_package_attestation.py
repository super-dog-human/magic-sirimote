"""Read-only verification for the larger post-connect receiver package.

Pinned files and package metadata are verified; extra files are not excluded.
Nothing here proves a process is running or a package is registered.
"""
import runtime_bundle as bundle
import hashlib,json,re
import local_attestation as att

def package_matches(app_path,pkg_path,record):
 if type(record) is dict and record.get('schema')=='bundled-role-v1':return bundle.package_matches(app_path,pkg_path,record)
 if type(record) is not dict or type(record.get('files')) is not dict or not 1<=len(record['files'])<=200 or type(record.get('appId')) is not str or type(record.get('packageInfoSha256')) is not str:raise ValueError('invalid receiver package pin')
 att._directory(app_path);att._directory(pkg_path)
 for name,digest in record['files'].items():
  if type(digest) is not str or not re.fullmatch('[a-f0-9]{64}',digest) or hashlib.sha256(att._read_file(app_path,name)).hexdigest()!=digest:return False
 info=json.loads(att._read_file(app_path,'appinfo.json'));pkg=att._read_file(pkg_path,'packageinfo.json')
 return info.get('id')==record['appId'] and hashlib.sha256(pkg).hexdigest()==record['packageInfoSha256'] and json.loads(pkg).get('id')==record['appId']
