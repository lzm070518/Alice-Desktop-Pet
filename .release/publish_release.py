"""Publish verified user-edition assets from a temporary delivery branch.

The application source, developer edition and maintenance credentials are not
part of this workflow. Existing published releases are never changed or deleted.
"""
from pathlib import Path, PurePosixPath
import hashlib,json,os,re,subprocess

def api(path):
    return json.loads(subprocess.check_output(['gh','api',path],text=True))

manifest=json.loads(Path('.release/assets.json').read_text())
repo=os.environ['GITHUB_REPOSITORY']
assert repo==manifest['repository']
assert manifest['edition']=='user' and re.fullmatch(r'\d+\.\d+\.\d+',manifest['version'])
assert manifest['tag']=='v'+manifest['version']
base='repos/'+repo+'/releases/'+str(manifest['release_id'])
release=api(base)
assert release['tag_name']==manifest['tag']
expected={a['name']:a for a in manifest['assets']}
assert len(expected)==len(manifest['assets']) and not any('Developer' in name for name in expected)

def verified_assets():
    assets=api(base+'/assets')
    assert set(a['name'] for a in assets)==set(expected), 'Unexpected or missing public asset'
    for asset in assets:
        want=expected[asset['name']]
        assert asset['state']=='uploaded' and asset['size']==want['bytes']
        assert asset.get('digest')=='sha256:'+want['sha256'], 'Remote asset digest mismatch'
    return assets

if not release['draft']:
    verified_assets()
    print('Already published and verified; history preserved:',release['html_url'])
    raise SystemExit(0)

work=Path(os.environ['RUNNER_TEMP'])/('alice-user-release-'+manifest['version'])
work.mkdir(exist_ok=True)
for asset in manifest['assets']:
    assert PurePosixPath(asset['name']).name==asset['name']
    target=work/asset['name'];total=hashlib.sha256();size=0
    with target.open('wb') as out:
        for part in asset['parts']:
            source=Path(part['path'])
            assert source.parts[:2]==('.release','data') and '..' not in source.parts
            assert source.is_file() and not source.is_symlink()
            digest=hashlib.sha256();part_size=0
            with source.open('rb') as src:
                while block:=src.read(2*1024*1024):
                    out.write(block);total.update(block);digest.update(block)
                    part_size+=len(block);size+=len(block)
            assert part_size==part['bytes'] and digest.hexdigest()==part['sha256'], 'Delivery chunk changed'
    assert size==asset['bytes'] and total.hexdigest()==asset['sha256'], 'Installer reconstruction changed'
    print('Verified local asset:',asset['name'],size,flush=True)

for name,want in expected.items():
    present=next((a for a in api(base+'/assets') if a['name']==name),None)
    if present:
        if present['state']=='uploaded' and present['size']==want['bytes'] and present.get('digest')=='sha256:'+want['sha256']:
            continue
        # Only an incomplete same-name asset of this still-draft release may be
        # retried. This never removes a published release or historical file.
        assert api(base)['draft']
        subprocess.run(['gh','api','--method','DELETE','repos/'+repo+'/releases/assets/'+str(present['id'])],check=True)
    subprocess.run(['gh','release','upload',manifest['tag'],str(work/name),'--repo',repo],check=True)
    print('Uploaded:',name,flush=True)

assets=verified_assets()
request=work/'publish.json'
request.write_text(json.dumps({'tag_name':manifest['tag'],'draft':False,'prerelease':False,'make_latest':'true','name':manifest['title'],'body':manifest['body']},ensure_ascii=False))
published=json.loads(subprocess.check_output(['gh','api','--method','PATCH',base,'--input',str(request)],text=True))
assert not published['draft'] and published['tag_name']==manifest['tag'] and published['name']==manifest['title']
print('Published:',published['html_url'],flush=True)
Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('# Alice '+manifest['version']+' user edition\n\n'+published['html_url']+'\n\nAll '+str(len(assets))+' assets verified against their SHA256 digests. Historical releases retained.\n')
