"""Build optional source-checked CPython caches with a chosen interpreter."""
import base64,hashlib,importlib.util,json,re,subprocess,sys,tempfile
from pathlib import Path,PurePosixPath


def _worker(request):
    import py_compile
    if sys.implementation.name!='cpython':raise ValueError('CPython is required for import caches')
    records=[]
    with tempfile.TemporaryDirectory(prefix='sirimote-bytecode-') as directory:
        for name,encoded in request['sources'].items():
            source=base64.b64decode(encoded,validate=True)
            path=Path(directory)/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(source)
            cached=py_compile.compile(str(path),dfile=request['installedRoot']+'/'+name,doraise=True,optimize=0,
                invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
            relative=Path(cached).relative_to(directory).as_posix()
            records.append({'path':relative,'source':name,'sourceSha256':hashlib.sha256(source).hexdigest(),
                            'data':base64.b64encode(Path(cached).read_bytes()).decode()})
    return {'tag':sys.implementation.cache_tag,'magic':importlib.util.MAGIC_NUMBER.hex(),
            'python':sys.version.split()[0],'files':records}


def compile_files(files,python,installed_root):
    sources={name:data for name,data in files.items() if re.fullmatch(r'(?:runtime|native)/[A-Za-z0-9_]+\.py',name)}
    if not sources or len(sources)>192:raise ValueError('Unexpected bytecode source inventory')
    request={'installedRoot':installed_root,'sources':{name:base64.b64encode(data).decode() for name,data in sources.items()}}
    result=subprocess.run([str(python),'-I','-B',str(Path(__file__).resolve()),'--worker'],input=json.dumps(request),
                          capture_output=True,text=True,timeout=60)
    if result.returncode:raise ValueError('Bytecode compiler failed: '+result.stderr[-300:])
    if len(result.stdout)>8*1024*1024:raise ValueError('Bytecode output too large')
    value=json.loads(result.stdout);tag=value['tag'];magic=bytes.fromhex(value['magic'])
    if not re.fullmatch(r'cpython-3[0-9]{1,2}',tag) or len(magic)!=4 or len(value['files'])!=len(sources):
        raise ValueError('Invalid bytecode compiler metadata')
    import _imp
    caches={};seen=set()
    for record in value['files']:
        name=record['source']
        if name not in sources or name in seen or record['sourceSha256']!=hashlib.sha256(sources[name]).hexdigest():
            raise ValueError('Bytecode source mismatch')
        seen.add(name);path=PurePosixPath(name)
        expected=str(path.parent/'__pycache__'/(path.stem+'.'+tag+'.pyc'))
        data=base64.b64decode(record['data'],validate=True)
        header=magic+(3).to_bytes(4,'little')+_imp.source_hash(int.from_bytes(magic,'little'),sources[name])
        if record['path']!=expected or not 16<len(data)<=524288 or data[:16]!=header:
            raise ValueError('Bytecode header or path mismatch')
        caches[expected]=data
    return caches,{'cacheTag':tag,'magic':magic.hex(),'python':value['python'],'files':len(caches),'invalidation':'checked-hash'}


if __name__=='__main__':
    if sys.argv[1:]!=['--worker']:raise SystemExit('Build helper requires --worker')
    print(json.dumps(_worker(json.load(sys.stdin)),sort_keys=True,separators=(',',':')))
