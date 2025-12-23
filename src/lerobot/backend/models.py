import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class TeleopSession(Base):
    __tablename__ = "teleop_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    robot_id = Column(String, index=True)
    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    fps = Column(Integer)
    meta_info = Column(JSON, nullable=True) # 카메라 설정 등 메타 정보

    frames = relationship("TeleopFrame", back_populates="session")
    videos = relationship("VideoChunk", back_populates="session") # [NEW] 영상 조각들

class TeleopFrame(Base):
    __tablename__ = "teleop_frames"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("teleop_sessions.id"))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    frame_index = Column(Integer)
    data = Column(JSON) # 관절 각도(Observation) 및 명령(Action) 데이터 통합 저장

    session = relationship("TeleopSession", back_populates="frames")

class VideoChunk(Base): # [NEW] 영상 파일 관리용 테이블
    __tablename__ = "video_chunks"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("teleop_sessions.id"))
    camera_key = Column(String) # e.g. "laptop", "phone"
    file_path = Column(String) # 서버 내 파일 경로 (filesystem path)
    start_timestamp = Column(Float) # 영상 시작 시간 (Unix Timestamp)
    end_timestamp = Column(Float) # 영상 끝 시간
    
    session = relationship("TeleopSession", back_populates="videos")
