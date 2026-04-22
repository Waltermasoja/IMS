
# Project Overview

This is a Django-based Inventory Management System (IMS). It provides functionalities for managing inventory, sales, customers, suppliers, and import orders. The system also includes features for handling returns, damaged goods, and basic accounting.

## Main Technologies

*   **Backend:** Django
*   **Frontend:** HTML, CSS, JavaScript, Bootstrap, Plotly.js
*   **Database:** SQLite (default), with an option for MySQL

## Architecture

The project follows a standard Django architecture:

*   **`inventorySystem`:** The main project directory, containing settings and project-level URL configurations.
*   **`inventory`:** The core application, containing models, views, forms, and templates for all inventory-related functionalities.
*   **`templates`:** Contains all the HTML templates for the application.
*   **`static`:** Contains static files like CSS, JavaScript, and images.

# Building and Running

To build and run this project, follow these steps:

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Apply Migrations:**
    ```bash
    python manage.py migrate
    ```

3.  **Run the Development Server:**
    ```bash
    python manage.py runserver
    ```

The application will be accessible at `http://127.0.0.1:8000/`.

# Development Conventions

*   **Coding Style:** The project follows the standard PEP 8 style guide for Python code.
*   **Testing:** The project has a `tests.py` file in the `inventory` app, but it is currently empty.
*   **Contribution Guidelines:** There are no explicit contribution guidelines in the project.
