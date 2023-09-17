import datetime

from sqlalchemy import Boolean, Column, Integer, String

from repository.database import database, session


class Emoji(database.base):
    __tablename__ = "emoji"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    url = Column(String)
    deprecated = Column(Boolean)

    @classmethod
    def get_emojis(cls) -> bool:
        """Set new date of last error.
        :return: Whether the date got updated or not.
        """
        query = cls.get()
        today = datetime.date.today()
        if getattr(query, "date", None) == today:
            return False

        if query is None:
            query = cls()
            session.add(query)
        query.date = today
        session.commit()
        return True
