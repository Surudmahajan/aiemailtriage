FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (better Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Create the CSV database file with headers if it doesn't exist
RUN python -c "
from pathlib import Path
import csv
db = Path('triage_database.csv')
if not db.exists():
    with open(db, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow(['Timestamp','Ticket ID','Category','Priority','Sentiment','Customer Intent','Assigned Team','Estimated Response Time','Confidence','Human Decision'])
print('Database ready.')
"

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
