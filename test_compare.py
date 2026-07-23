"""Compare monkey-patched vs explicit proxies for dashscope."""
import sys
sys.path.insert(0, '/ragflow')
from rag.llm import embedding_model
import dashscope
import requests

# Test 1: raw requests (should use monkey-patch)
print('=== Test 1: requests.post (monkey-patched) ===')
try:
    r = requests.post(
        'https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding',
        json={'model': 'text-embedding-v3', 'input': {'texts': ['test']}},
        headers={'Authorization': 'Bearer sk-test'},
        timeout=10,
    )
    print(f'status={r.status_code}')
except Exception as e:
    print(f'Error: {type(e).__name__}: {str(e)[:100]}')

# Test 2: requests with explicit proxies=None
print('=== Test 2: requests.post (explicit proxies=None) ===')
try:
    r = requests.post(
        'https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding',
        json={'model': 'text-embedding-v3', 'input': {'texts': ['test']}},
        headers={'Authorization': 'Bearer sk-test'},
        timeout=10,
        proxies={'http': None, 'https': None},
    )
    print(f'status={r.status_code}')
except Exception as e:
    print(f'Error: {type(e).__name__}: {str(e)[:100]}')

# Test 3: dashscope SDK
print('=== Test 3: dashscope SDK ===')
try:
    resp = dashscope.TextEmbedding.call(
        model='text-embedding-v3',
        input=['test'],
        api_key='sk-test',
        text_type='document',
    )
    print(f'status={resp.status_code}')
except Exception as e:
    print(f'Error: {type(e).__name__}: {str(e)[:100]}')

print('All tests done.')
