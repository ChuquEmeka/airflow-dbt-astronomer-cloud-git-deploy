FROM quay.io/astronomer/astro-runtime:12.7.1

# Set environment variables
ENV VENV_PATH="/usr/local/airflow/dbt_venv"
ENV PATH="$VENV_PATH/bin:$PATH" 

# Install dbt into a virtual environment and upgrade pip + setuptools
RUN python -m venv $VENV_PATH && \
    source $VENV_PATH/bin/activate && \
    pip install --upgrade pip setuptools && \
    pip install --no-cache-dir dbt-bigquery==1.5.3 pandas Faker pyarrow numpy && \
    deactivate



# Install dependencies from requirements.txt
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# Install astronomer-cosmos explicitly
# RUN pip install --no-cache-dir astronomer-cosmos==1.8.2 pydantic
# Store environment activation script inside Airflow home
RUN echo "source $VENV_PATH/bin/activate" > /usr/local/airflow/dbt_env.sh
RUN chmod +x /usr/local/airflow/dbt_env.sh