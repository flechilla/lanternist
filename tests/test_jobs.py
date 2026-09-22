"""The job queue: one job at a time, and nothing a user does to a story stops the queue."""

from lanternist.db import Job, Story
from lanternist.jobs import Runner


async def test_deleting_a_story_while_its_job_runs_keeps_the_queue_going(cfg, db):
    with db.session() as s:
        s.add(Story(id="s1", slug="a", title="A", version=0))
        s.commit()
    runner = Runner(cfg, db)
    job = runner.enqueue("s1", "board", 1)

    async def delete_the_story(job, progress):  # what DELETE /api/stories does meanwhile
        with db.session() as s:
            s.query(Job).filter_by(story_id="s1").delete()
            s.delete(s.get(Story, "s1"))
            s.commit()
        return {}

    runner.execute = delete_the_story
    await runner.run(job.id)  # raised AttributeError on the missing row, which ended the queue's loop
    with db.session() as s:
        assert s.query(Job).count() == 0
    assert runner.current is None
