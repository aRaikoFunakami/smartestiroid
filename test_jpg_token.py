import base64
import json
from openai import OpenAI

# init client
client = OpenAI()

# load image as base64
with open("agent_screenshot.jpg", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode("utf-8")

# call API
resp = client.chat.completions.create(
    model="gpt-4.1",   # マルチモーダル対応モデル
    messages=[
        {
            "role": "user",
            "content": [
                #{"type": "text", "text": "この画像の内容を説明してください"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                }
            ],
        }
    ],
)

# dump raw response to stdout
print(json.dumps(resp.to_dict(), ensure_ascii=False, indent=2))