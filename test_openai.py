import os
from openai import OpenAI

MODEL = "gpt-5.6-luna"

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise RuntimeError("OPENAI_API_KEY não está definida.")

client = OpenAI(api_key=api_key)

print("=" * 70)
print("TESTE MÍNIMO OPENAI")
print("=" * 70)
print(f"Modelo: {MODEL}")
print()

response = client.responses.create(
    model=MODEL,
    input="Responda apenas: PLANAPP OPENAI OK",
    reasoning={"effort": "none"},
)

print("Resposta:")
print(response.output_text)

print()
print("Usage:")
print(response.usage)

print()
print("=" * 70)

if "PLANAPP OPENAI OK" in response.output_text:
    print("✅ TESTE OPENAI CONCLUÍDO COM SUCESSO")
else:
    print("⚠️ API respondeu, mas o texto esperado não foi encontrado.")