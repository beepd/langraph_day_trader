from pydantic import BaseModel, Field

from llm_setup import build_llm, PROVIDER, MODEL


class Check(BaseModel):
    answer: int = Field(description="The result of the sum")
    explanation: str = Field(description="One short sentence")


print(f"Testing {PROVIDER} / {MODEL} ...")
llm = build_llm()
result = llm.with_structured_output(Check).invoke("What is 17 + 25?")
print(result)
print("OK: the model can fill in a form" if result.answer == 42 else "Unexpected answer, do not use this model yet")