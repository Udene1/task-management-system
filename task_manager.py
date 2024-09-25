import datetime
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict
from enum import Enum
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import configparser

class Priority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3

@dataclass
class Task:
    id: int
    title: str
    description: str
    deadline: datetime.date
    priority: Priority
    assigned_to: str
    status: str = "Not Started"
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)

    def to_dict(self):
        return {
            **asdict(self),
            'priority': self.priority.name,
            'deadline': self.deadline.isoformat(),
            'created_at': self.created_at.isoformat()
        }

@dataclass
class TeamMember:
    name: str
    email: str
    tasks: List[Task] = field(default_factory=list)
    workload: int = 0

    def to_dict(self):
        return {
            'name': self.name,
            'email': self.email,
            'workload': self.workload
        }

class TaskManager:
    def __init__(self, db_name='task_manager.db'):
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name)
        self.create_tables()
        self.load_data()
        self.config = self.load_config()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY,
                title TEXT,
                description TEXT,
                deadline DATE,
                priority TEXT,
                assigned_to TEXT,
                status TEXT,
                created_at DATETIME
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS team_members (
                name TEXT PRIMARY KEY,
                email TEXT,
                workload INTEGER
            )
        ''')
        self.conn.commit()

    def load_data(self):
        self.tasks = []
        self.team_members = {}
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tasks")
        for row in cursor.fetchall():
            task = Task(
                id=row[0],
                title=row[1],
                description=row[2],
                deadline=datetime.date.fromisoformat(row[3]),
                priority=Priority[row[4]],
                assigned_to=row[5],
                status=row[6],
                created_at=datetime.datetime.fromisoformat(row[7])
            )
            self.tasks.append(task)

        cursor.execute("SELECT * FROM team_members")
        for row in cursor.fetchall():
            team_member = TeamMember(name=row[0], email=row[1], workload=row[2])
            self.team_members[row[0]] = team_member

    def save_data(self):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM tasks")
        cursor.execute("DELETE FROM team_members")
        
        for task in self.tasks:
            cursor.execute('''
                INSERT INTO tasks (id, title, description, deadline, priority, assigned_to, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (task.id, task.title, task.description, task.deadline.isoformat(), task.priority.name,
                  task.assigned_to, task.status, task.created_at.isoformat()))

        for member in self.team_members.values():
            cursor.execute('''
                INSERT INTO team_members (name, email, workload)
                VALUES (?, ?, ?)
            ''', (member.name, member.email, member.workload))

        self.conn.commit()

    def load_config(self):
        config = configparser.ConfigParser()
        if os.path.exists('config.ini'):
            config.read('config.ini')
        else:
            config['EMAIL'] = {'sender_email': '', 'sender_password': ''}
            with open('config.ini', 'w') as configfile:
                config.write(configfile)
        return config    
    
    def save_config(self):
        with open('config.ini', 'w') as configfile:
            self.config.write(configfile)

    def add_task(self, title: str, description: str, deadline: datetime.date, priority: Priority, assigned_to: str) -> Task:
        task_id = max([task.id for task in self.tasks], default=0) + 1
        task = Task(task_id, title, description, deadline, priority, assigned_to)
        self.tasks.append(task)
        if assigned_to not in self.team_members:
            raise ValueError(f"Team member {assigned_to} does not exist")
        self.team_members[assigned_to].tasks.append(task)
        self.team_members[assigned_to].workload += priority.value
        self.save_data()
        return task

    def update_task_status(self, task_id: int, new_status: str):
        for task in self.tasks:
            if task.id == task_id:
                task.status = new_status
                self.save_data()
                break

    def get_tasks_by_priority(self, priority: Priority) -> List[Task]:
        return [task for task in self.tasks if task.priority == priority]

    def get_upcoming_deadlines(self, days: int) -> List[Task]:
        today = datetime.date.today()
        deadline = today + datetime.timedelta(days=days)
        return [task for task in self.tasks if today <= task.deadline <= deadline]

    def generate_to_do_list(self, team_member: str) -> List[Task]:
        if team_member in self.team_members:
            return sorted(self.team_members[team_member].tasks, key=lambda x: (x.priority.value, x.deadline), reverse=True)
        return []

    def allocate_task(self, task: Task):
        team_member = min(self.team_members.values(), key=lambda x: x.workload)
        task.assigned_to = team_member.name
        team_member.tasks.append(task)
        team_member.workload += task.priority.value
        self.save_data()

    def add_team_member(self, name: str, email: str):
        if name not in self.team_members:
            self.team_members[name] = TeamMember(name, email)
            self.save_data()
        else:
            raise ValueError(f"Team member {name} already exists")

    def generate_productivity_report(self) -> Dict:
        report = {}
        for member in self.team_members.values():
            completed_tasks = len([task for task in member.tasks if task.status == "Completed"])
            total_tasks = len(member.tasks)
            if total_tasks > 0:
                completion_rate = completed_tasks / total_tasks
            else:
                completion_rate = 0
            report[member.name] = {
                "completed_tasks": completed_tasks,
                "total_tasks": total_tasks,
                "completion_rate": completion_rate,
                "workload": member.workload
            }
        return report

    def send_reminder_email(self, task: Task):
        sender_email = self.config['EMAIL']['sender_email']
        sender_password = self.config['EMAIL']['sender_password']

        if not sender_email or not sender_password:
            print("Email configuration is not set up. Please use the 'Configure Email' option in the main menu.")
            return

        receiver_email = self.team_members[task.assigned_to].email
        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = receiver_email
        message["Subject"] = f"Reminder: Task '{task.title}' Due Soon"

        body = f"""
        Dear {task.assigned_to},

        This is a reminder that the following task is due soon:

        Title: {task.title}
        Description: {task.description}
        Deadline: {task.deadline}
        Priority: {task.priority.name}

        Please ensure this task is completed on time.

        Best regards,
        Task Management System
        """

        message.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, receiver_email, message.as_string())
            print(f"Reminder email sent to {task.assigned_to}")
        except Exception as e:
            print(f"Failed to send email: {str(e)}")

    def send_reminders(self):
        today = datetime.date.today()
        upcoming_tasks = [task for task in self.tasks if (task.deadline - today).days <= 2 and task.status != "Completed"]
        for task in upcoming_tasks:
            self.send_reminder_email(task)

class CLI:
    def __init__(self):
        self.task_manager = TaskManager()

    def run(self):
        while True:
            self.display_menu()
            choice = input("Enter your choice: ")
            self.handle_choice(choice)

    def display_menu(self):
        print("\n--- Task Management System ---")
        print("1. Add Task")
        print("2. Update Task Status")
        print("3. View Tasks by Priority")
        print("4. View Upcoming Deadlines")
        print("5. Generate To-Do List")
        print("6. Add Team Member")
        print("7. Generate Productivity Report")
        print("8. Send Reminders")
        print("9. Configure Email")
        print("10. Exit")

    def handle_choice(self, choice):
        if choice == "1":
            self.add_task()
        elif choice == "2":
            self.update_task_status()
        elif choice == "3":
            self.view_tasks_by_priority()
        elif choice == "4":
            self.view_upcoming_deadlines()
        elif choice == "5":
            self.generate_to_do_list()
        elif choice == "6":
            self.add_team_member()
        elif choice == "7":
            self.generate_productivity_report()
        elif choice == "8":
            self.send_reminders()
        elif choice == "9":
            self.configure_email()
        elif choice == "10":
            print("Exiting...")
            exit()
        else:
            print("Invalid choice. Please try again.")

    def add_task(self):
        title = input("Enter task title: ")
        description = input("Enter task description: ")
        deadline = input("Enter deadline (YYYY-MM-DD): ")
        priority = input("Enter priority (LOW/MEDIUM/HIGH): ")
        assigned_to = input("Enter assigned team member: ")

        try:
            deadline = datetime.date.fromisoformat(deadline)
            priority = Priority[priority.upper()]
            task = self.task_manager.add_task(title, description, deadline, priority, assigned_to)
            print(f"Task added successfully. Task ID: {task.id}")
        except ValueError as e:
            print(f"Error: {str(e)}")

    def update_task_status(self):
        task_id = int(input("Enter task ID: "))
        new_status = input("Enter new status: ")
        self.task_manager.update_task_status(task_id, new_status)
        print("Task status updated successfully.")

    def view_tasks_by_priority(self):
        priority = input("Enter priority (LOW/MEDIUM/HIGH): ")
        try:
            priority = Priority[priority.upper()]
            tasks = self.task_manager.get_tasks_by_priority(priority)
            for task in tasks:
                print(f"ID: {task.id}, Title: {task.title}, Deadline: {task.deadline}, Assigned to: {task.assigned_to}")
        except KeyError:
            print("Invalid priority.")

    def view_upcoming_deadlines(self):
        days = int(input("Enter number of days to look ahead: "))
        tasks = self.task_manager.get_upcoming_deadlines(days)
        for task in tasks:
            print(f"ID: {task.id}, Title: {task.title}, Deadline: {task.deadline}, Assigned to: {task.assigned_to}")

    def generate_to_do_list(self):
        team_member = input("Enter team member name: ")
        tasks = self.task_manager.generate_to_do_list(team_member)
        for task in tasks:
            print(f"ID: {task.id}, Title: {task.title}, Priority: {task.priority.name}, Deadline: {task.deadline}")

    def add_team_member(self):
        name = input("Enter team member name: ")
        email = input("Enter team member email: ")
        try:
            self.task_manager.add_team_member(name, email)
            print(f"Team member {name} added successfully.")
        except ValueError as e:
            print(f"Error: {str(e)}")

    def generate_productivity_report(self):
        report = self.task_manager.generate_productivity_report()
        for member, stats in report.items():
            print(f"\nTeam Member: {member}")
            print(f"Completed Tasks: {stats['completed_tasks']}")
            print(f"Total Tasks: {stats['total_tasks']}")
            print(f"Completion Rate: {stats['completion_rate']:.2%}")
            print(f"Workload: {stats['workload']}")

    def send_reminders(self):
        self.task_manager.send_reminders()
        print("Reminders sent for tasks due in 2 days.")

    def configure_email(self):
        sender_email = input("Enter sender email: ")
        sender_password = input("Enter sender password: ")
        self.task_manager.config['EMAIL']['sender_email'] = sender_email
        self.task_manager.config['EMAIL']['sender_password'] = sender_password
        self.task_manager.save_config()
        print("Email configuration saved.")

if __name__ == "__main__":
    cli = CLI()
    cli.run()