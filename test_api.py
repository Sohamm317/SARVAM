import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.environ.get("LLM_API_KEY"),
                 base_url = os.environ.get("LLM_BASE_URL"))

response = client.chat.completions.create(
    model=os.environ.get("LLM_MODEL"),
    messages=[
        {"role":"system", "content":"You speak like Shakespeare."},
        {"role":"user", "content":"What is the meaning of life?"},
    ],
    max_tokens=200,
)

print(response.choices[0].message.content)