# Database session Management
This module provides functionality for managing database connections and sessions using SQLAlchemy. It includes functions to create a new database engine, establish sessions, and handle session lifecycle.

## Database Engine
To connect to the database, we create a SQLAlchemy engine using the database URL specified in the application settings. The `create_engine` function is used to create the engine with appropriate configurations for synchronous and asynchronous operations.

## Sync Session
The `get_sync_session` function is a context manager that yields a synchronous SQLAlchemy session. It ensures that the session is properly closed after use. To use this function, simply call it within a `with` statement:

```python
with get_sync_session() as session:
    # Use the session here
```

## Async Session
The `get_async_session` function is an asynchronous context manager that yields an asynchronous SQLAlchemy session. It ensures that the session is properly closed after use. These asynchronous sessions are useful for applications that require non-blocking database operations, for example the dashboard application or a future FastAPI.
To use this function with FastAPI, you can define it as a dependency:

```python
from typing import Annotated
from fastapi import Depends, FastAPI
from database.session import get_async_session

app = FastAPI()

async def some_endpoint(session: Annotated[AsyncSession, Depends(get_async_session)]):
    # Define logic here
    session.execute(...)
```