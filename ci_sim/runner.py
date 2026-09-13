import hashlib, json, os, sys
repo=os.environ.get('REPLICA_REPOSITORY','unknown'); workflow=os.environ.get('REPLICA_SOURCE_WORKFLOW','unknown'); job=os.environ.get('REPLICA_SOURCE_JOB','unknown'); scope=os.environ.get('REPLICA_SCOPE','private'); matrix=os.environ.get('MATRIX_JSON','{}'); failure=os.environ.get('SIMULATE_FAILURE','')
identity=f'{repo}:{workflow}:{job}:{matrix}'
result='failure' if failure and (failure in (job,workflow,repo) or failure == 'all') else 'success'
event={'repo':repo,'workflow':workflow,'job':job,'scope':scope,'matrix':matrix,'result':result,'test_key':'replica-'+hashlib.sha256(identity.encode()).hexdigest()[:16]}
print(json.dumps(event, sort_keys=True))
if result != 'success': sys.exit(1)
