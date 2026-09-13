import json, pathlib, sys
root=pathlib.Path(__file__).resolve().parents[1]; catalog=json.loads((root/'test-catalog.json').read_text(encoding='utf-8')); failure=sys.argv[1] if len(sys.argv)>1 else ''; results=[]
for item in catalog:
    cases=1
    for values in item.get('matrix',{}).values(): cases *= max(1,len(values)) if isinstance(values,list) else 1
    for index in range(cases): results.append({'id':item['id'],'scope':item['scope'],'case':index,'result':'FAIL' if failure and (failure in item['id'] or failure=='all') else 'PASS'})
failed=[r for r in results if r['result']!='PASS']; print(json.dumps({'total':len(results),'passed':len(results)-len(failed),'failed':failed}, indent=2)); sys.exit(1 if failed else 0)
