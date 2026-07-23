with open('/home/zhengkundeng/ragflow/docker/entrypoint.sh', 'r') as f:
    lines = f.readlines()

target = '"" api/ragflow_server.py  </dev/null'
replacement = '        "$PY" api/ragflow_server.py ${INIT_SUPERUSER_ARGS} </dev/null'

for i, line in enumerate(lines):
    if target in line:
        lines[i] = replacement + '\n'
        print(f'Fixed line {i+1}')
        break

with open('/home/zhengkundeng/ragflow/docker/entrypoint.sh', 'w') as f:
    f.writelines(lines)
print('Done')
