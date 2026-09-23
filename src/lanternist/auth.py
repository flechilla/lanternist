"""Who is asking. The local edition has one user, `local`, and no sign-in. The hosted edition knows a
person by the session their sign-in started (plans/ACCOUNTS_PLAN.md §1.4); in fake mode a test may
name the user in a header instead, so tests can act as two people.

Routes take the user as `me: Me`, and pass `me.id` to every `Database` method that reads or changes
a row a user owns.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .db import LOCAL, User

FAKE_USER = "X-Lanternist-User"  # fake mode only: the name of the user a test acts as


def current_user(request: Request) -> User:
    cfg, db = request.app.state.cfg, request.app.state.db
    if not cfg.hosted_edition:
        user = db.user(LOCAL)
        if user is None:  # only a library whose migration didn't run: the app migrates at start
            raise HTTPException(500, "the library has no local user: restart Lanternist to migrate it")
        return user
    if cfg.fake_engines and (name := request.headers.get(FAKE_USER)):
        return db.sign_in(f"fake:{name}", f"{name}@example.com")
    raise HTTPException(401, "sign in first")


Me = Annotated[User, Depends(current_user)]
