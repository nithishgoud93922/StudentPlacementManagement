\# PlacementHub – Student Placement Management and Analytics System



PlacementHub is a web-based platform developed using Flask and MySQL to simplify and manage campus placement activities. It provides separate services for students, recruiters, and placement officers.



\## Features



\### Student Module

\- Student registration and login.

\- Student profile management.

\- Browse available job opportunities.

\- Apply for suitable jobs.

\- Track application status.

\- AI-powered resume generation.



\### Recruiter Module

\- Recruiter registration and login.

\- Post and manage job opportunities.

\- View students who applied for jobs.

\- Access applicant details.

\- Update application status.

\- Print applicant details.



\### Placement Officer Module

\- Manage student information.

\- Monitor placement activities.

\- View placement analytics.

\- Generate placement reports.



\## Technologies Used



| Category | Technologies |

|---|---|

| Frontend | HTML, CSS, JavaScript |

| Backend | Python, Flask |

| Database | MySQL |

| ORM | Flask-SQLAlchemy |

| AI Integration | Google Gemini API |

| Version Control | Git and GitHub |



\## Project Structure



```text

StudentPlacementManagement/

│

├── app.py

├── requirements.txt

├── sql.sql

├── README.md

├── templates/

├── static/

└── .gitignore

```



\## Installation and Setup



\### 1. Clone the repository



```bash

git clone https://github.com/nithishgoud93922/StudentPlacementManagement.git

```



\### 2. Navigate to the project folder



```bash

cd StudentPlacementManagement

```



\### 3. Create a virtual environment



```bash

python -m venv venv

```



\### 4. Activate the virtual environment



Windows PowerShell:



```powershell

.\\venv\\Scripts\\Activate.ps1

```



\### 5. Install dependencies



```bash

pip install -r requirements.txt

```



\### 6. Configure environment variables



Create an `app.env` file in the project root and configure your own database credentials and Gemini API key according to the variables expected by `app.py`.



Never upload this file to GitHub.



\### 7. Set up MySQL



Create the database and execute the SQL commands provided in `sql.sql`. Configure your MySQL connection details in `app.env`.



\### 8. Run the application



```bash

python app.py

```



Open your browser and visit:



```text

http://127.0.0.1:5000

```



\## Project Objective



The main objective of PlacementHub is to provide a centralized platform for managing student placement activities, improving communication between students and recruiters, and helping placement officers monitor recruitment performance.



\## Developer



\*\*Abbagouni Nithish Goud\*\*



GitHub: https://github.com/nithishgoud93922



\## Repository



https://github.com/nithishgoud93922/StudentPlacementManagement



