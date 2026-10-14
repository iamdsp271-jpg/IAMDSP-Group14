IAMDSP - Intelligent Academic Management and Decision Support Platform
Case study: IPAM Extra-Mural Studies, University of Sierra Leone
Final Year Project - Group Fourteen (14) - Diploma in ICT - 2026
Supervisor: Mr. Oluwatosin B. Ayorinde

Group members
  Mohamed Ramadan Jalloh (16061)   Michael Sillah (16187)   Samuel Sundima Gbani (12275)
  Sahr Bangallie (16649)           Mohamed Lamin Turay (16639)

HOW TO RUN (short version)
  1. Install Python 3.11 or 3.12 from python.org (tick "Add python.exe to PATH").
  2. Open this folder in VS Code, open the Terminal (Terminal > New Terminal) and type:
        python -m venv venv
        venv\Scripts\activate          (Mac/Linux:  source venv/bin/activate)
        pip install -r requirements.txt
        python app.py
  3. Open http://127.0.0.1:5000 in your browser.
  (On Windows you can also just double-click run_windows.bat)

LOGIN ACCOUNTS (sample data)
  Role                  Username              Password
  System Administrator  Group Fourteen        IAMDSP_PASSCODE      (group leader: Mohamed Ramadan Jalloh)
  Management            ibrahim.kamara        Ipam@2026
  Coordinator Freetown  michael.sillah        Ipam@2026
  Coordinator Bo        sahr.bangallie        Ipam@2026
  Lecturer Freetown     samuel.gbani          Ipam@2026
  Lecturer Freetown     mohamed.turay         Ipam@2026
  Student (example)     ipam/em/fr/2025/001   Ipam@2026   (every student: username = registration number)

NOTE: all students, marks and enrolment figures are SAMPLE DATA created by the project group for demonstration and testing.
They are not real IPAM records.

TESTS:   python -m unittest discover -s tests -v
RESET DATA (back to the original sample data):  python db.py
