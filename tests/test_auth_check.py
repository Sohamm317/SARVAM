import requests, os
from dotenv import load_dotenv
load_dotenv()

key = os.environ.get('SARVAM_CLONE_API_KEY')
url = 'https://api.sarvam.ai/text-to-speech'

payload = {
    'inputs': ['test'],
    'target_language_code': 'hi-IN',
    'speaker': 'shreya',
    'model': 'bulbul:v3',
    'enable_preprocessing': False
}

# 1. Empty key
r_empty = requests.post(url, headers={'api-subscription-key': '', 'Content-Type': 'application/json'}, json=payload)
print('1. Empty key:', r_empty.status_code, r_empty.text)

# 2. Missing header entirely
r_none = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload)
print('2. Missing header:', r_none.status_code, r_none.text)

# 3. Quoted key
r_quoted = requests.post(url, headers={'api-subscription-key': f'"{key}"', 'Content-Type': 'application/json'}, json=payload)
print('3. Quoted key:', r_quoted.status_code, r_quoted.text)

# 4. Correct key
r_good = requests.post(url, headers={'api-subscription-key': key, 'Content-Type': 'application/json'}, json=payload)
print('4. Correct key:', r_good.status_code)

