"""REST API for personal progress (``/v1/life``), used by the Jarvis home screen.

* ``GET    /v1/life/summary?today=``         profile, level, streak, progress, week
* ``GET    /v1/life/habits?day=``            habits with done-state for a day
* ``POST   /v1/life/habits``                 add a habit
* ``POST   /v1/life/habits/{id}/check``      mark done / not done for a day
* ``DELETE /v1/life/habits/{id}``            archive a habit
* ``GET    /v1/life/journal?start=&end=``    entries in a date range
* ``POST   /v1/life/journal``                add an entry
* ``DELETE /v1/life/journal/{id}``           delete an entry
* ``POST   /v1/life/focus``                  log a finished focus session
* ``GET|PUT /v1/life/profile``               display name and motto
* ``GET|PUT /v1/life/mission``               mission roadmap
* ``POST   /v1/life/mission/advance``        complete the current stage
* ``GET|POST /v1/life/bookmarks``             saved quotes

Days are the client's local ``YYYY-MM-DD``; they default to the server's today.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openjarvis.life.store import get_life_store

router = APIRouter(prefix="/v1/life", tags=["life"])


class HabitIn(BaseModel):
    name: str = Field(..., max_length=80)
    time: str = ""


class CheckIn(BaseModel):
    day: Optional[str] = None
    done: bool = True


class JournalIn(BaseModel):
    text: str = Field(..., max_length=5000)
    day: Optional[str] = None


class FocusIn(BaseModel):
    minutes: int
    label: str = ""
    day: Optional[str] = None


class ProfileIn(BaseModel):
    name: Optional[str] = None
    motto: Optional[str] = None


class MissionIn(BaseModel):
    title: str = Field(..., max_length=80)
    stages: List[str]


class BookmarkIn(BaseModel):
    quote: str = Field(..., max_length=300)
    saved: bool = True


def _call(fn: Callable[[], Any], missing: str = "Not found") -> Any:
    """Run a store call, mapping bad input to 400 and unknown ids to 404."""
    try:
        return fn()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=missing) from exc


@router.get("/summary")
async def summary(today: Optional[str] = None) -> Dict[str, Any]:
    return _call(lambda: get_life_store().summary(today=today))


@router.get("/habits")
async def list_habits(day: Optional[str] = None) -> Dict[str, Any]:
    return {"habits": _call(lambda: get_life_store().list_habits(day=day))}


@router.post("/habits")
async def add_habit(body: HabitIn) -> Dict[str, Any]:
    return _call(lambda: get_life_store().add_habit(body.name, time=body.time))


@router.post("/habits/{habit_id}/check")
async def check_habit(habit_id: str, body: CheckIn) -> Dict[str, Any]:
    _call(
        lambda: get_life_store().set_done(habit_id, body.day, body.done),
        "Habit not found",
    )
    return {"id": habit_id, "done": body.done}


@router.delete("/habits/{habit_id}")
async def archive_habit(habit_id: str) -> Dict[str, Any]:
    _call(lambda: get_life_store().archive_habit(habit_id), "Habit not found")
    return {"id": habit_id, "status": "archived"}


@router.get("/journal")
async def list_journal(start: str, end: str) -> Dict[str, Any]:
    return {"entries": _call(lambda: get_life_store().list_journal(start, end))}


@router.post("/journal")
async def add_journal(body: JournalIn) -> Dict[str, Any]:
    return _call(lambda: get_life_store().add_journal(body.text, day=body.day))


@router.delete("/journal/{entry_id}")
async def delete_journal(entry_id: str) -> Dict[str, Any]:
    _call(lambda: get_life_store().delete_journal(entry_id), "Entry not found")
    return {"id": entry_id, "status": "deleted"}


@router.post("/focus")
async def add_focus(body: FocusIn) -> Dict[str, Any]:
    return _call(
        lambda: get_life_store().add_focus(body.minutes, label=body.label, day=body.day)
    )


@router.get("/profile")
async def get_profile() -> Dict[str, str]:
    return get_life_store().profile()


@router.put("/profile")
async def put_profile(body: ProfileIn) -> Dict[str, str]:
    return get_life_store().update_profile(name=body.name, motto=body.motto)


@router.get("/mission")
async def get_mission() -> Optional[Dict[str, Any]]:
    return get_life_store().mission()


@router.put("/mission")
async def put_mission(body: MissionIn) -> Dict[str, Any]:
    return _call(lambda: get_life_store().set_mission(body.title, body.stages))


@router.post("/mission/advance")
async def advance_mission() -> Dict[str, Any]:
    return _call(lambda: get_life_store().advance_mission(), "No mission set")


@router.get("/bookmarks")
async def list_bookmarks() -> Dict[str, Any]:
    return {"quotes": get_life_store().bookmarks()}


@router.post("/bookmarks")
async def set_bookmark(body: BookmarkIn) -> Dict[str, Any]:
    _call(lambda: get_life_store().bookmark(body.quote, body.saved))
    return {"quote": body.quote, "saved": body.saved}


__all__ = ["router"]
