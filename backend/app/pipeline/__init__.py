"""The run pipeline: parse -> validate -> plan -> translate -> verify -> review -> execute -> audit -> publish."""

# Step indices shown by the frontend Stepper (keep in sync with STEP_LABELS in frontend/src/lib/types.ts)
S_PARSE, S_VALIDATE, S_GENERATE, S_VERIFY, S_REVIEW, S_EXECUTE, S_AUDIT, S_PUBLISH = range(8)
