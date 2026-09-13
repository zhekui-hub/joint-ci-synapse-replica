import json, os, subprocess
report={'schema_version':1,'joint_id':os.environ.get('JOINT_CI_ID','replica-manual'),'repo':os.environ.get('REPLICA_REPOSITORY','unknown'),'branch':os.environ.get('GITHUB_HEAD_REF','main'),'head_sha':os.environ.get('GITHUB_SHA','local'),'pr_number':os.environ.get('PR_NUMBER','0'),'ci_mode':'joint','joint_wait':os.environ.get('JOINT_WAIT','true').lower() == 'true','is_draft':False,'deps':json.loads(os.environ.get('JOINT_DEPS_JSON','{}')),'remote_tests':json.loads(os.environ.get('REMOTE_TESTS_JSON','[{"id":"public.smoke","params":{"profile":"default"}}]'))}
print(json.dumps(report, sort_keys=True))
if os.environ.get('JOINT_DISPATCH_TOKEN'):
    payload=json.dumps({'event_type':'joint_ci_report','client_payload':report})
    subprocess.run(['gh','api','-X','POST','repos/'+os.environ['JOINT_TARGET_REPO']+'/dispatches','--input','-'], input=payload, text=True, check=True)
