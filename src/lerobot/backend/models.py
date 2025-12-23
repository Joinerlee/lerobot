"""
LeRobot Backend Models

SQLAlchemy ORM 모델:
- Robot: 로봇 등록 및 상태 관리 (멀티로봇 지원)
- TeleopSession: 텔레오퍼레이션 세션
- TeleopFrame: 프레임별 관절 데이터
- VideoChunk: 비디오 파일 메타데이터
"""

import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Robot(Base):
    """로봇 등록 및 상태 관리. WebSocket 연결 시 자동 등록."""
    __tablename__ = "robots"

    id = Column(String, primary_key=True, index=True)  # robot_id (예: "robot_A")
    name = Column(String, nullable=True)
    robot_type = Column(String, nullable=True)  # 예: "so101_follower"
    status = Column(String, default="offline")  # online / offline / error
    last_heartbeat = Column(DateTime, nullable=True)
    ip_address = Column(String, nullable=True)
    meta_info = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    sessions = relationship("TeleopSession", back_populates="robot")


class TeleopSession(Base):
    """텔레오퍼레이션 세션. 연결 시작~종료까지 하나의 세션."""
    __tablename__ = "teleop_sessions"

    id = Column(Integer, primary_key=True, index=True)
    robot_id = Column(String, ForeignKey("robots.id"), index=True)
    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    fps = Column(Integer)
    frame_count = Column(Integer, default=0)
    meta_info = Column(JSON, nullable=True)  # 카메라 설정 등

    robot = relationship("Robot", back_populates="sessions")
    frames = relationship("TeleopFrame", back_populates="session")
    videos = relationship("VideoChunk", back_populates="session")


class TeleopFrame(Base):
    """프레임별 관절 데이터 (observation + action)."""
    __tablename__ = "teleop_frames"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("teleop_sessions.id"), index=True)
    robot_id = Column(String, ForeignKey("robots.id"), index=True)  # 멀티로봇 직접 참조
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    frame_index = Column(Integer)
    data = Column(JSON)  # 관절 각도 및 명령 데이터

    session = relationship("TeleopSession", back_populates="frames")
    robot = relationship("Robot")


class VideoChunk(Base):
    """영상 파일 메타데이터."""
    __tablename__ = "video_chunks"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("teleop_sessions.id"), index=True)
    robot_id = Column(String, ForeignKey("robots.id"), index=True)  # 멀티로봇 직접 참조
    camera_key = Column(String)  # 예: "laptop", "phone"
    file_path = Column(String)
    start_timestamp = Column(Float)
    end_timestamp = Column(Float)

    session = relationship("TeleopSession", back_populates="videos")
    robot = relationship("Robot")
