FROM public.ecr.aws/lambda/python:3.12

COPY analytics/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY analytics/dbt_runner.py ${LAMBDA_TASK_ROOT}/dbt_runner.py
COPY analytics/dbt ${LAMBDA_TASK_ROOT}/dbt

ENV DBT_PROJECT_DIR=${LAMBDA_TASK_ROOT}/dbt
ENV DBT_PROFILES_DIR=${LAMBDA_TASK_ROOT}/dbt

CMD ["dbt_runner.lambda_handler"]
