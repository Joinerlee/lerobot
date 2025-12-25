#!/usr/bin/env python3
"""
LeRobot 데이터셋 내보내기 스크립트

DB의 세션 데이터를 LeRobot 훈련 형식으로 변환합니다.
영상 포함 여부를 선택할 수 있습니다.

Usage:
    # 관절값만 내보내기
    python export_to_dataset.py --session_id 1 --repo_id user/dataset

    # 영상 포함 내보내기 (병합 스크립트 사용 권장)
    python -m scripts.merge_dataset --session_id 1 --repo_id user/dataset

Features:
    - 세션별 에피소드 내보내기
    - LeRobot 데이터셋 형식 변환
    - Hugging Face Hub 업로드 지원
"""

import argparse
import asyncio
from pathlib import Path

import torch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from lerobot.backend.core.config import settings
from lerobot.backend.core.logging import get_logger
from lerobot.backend.models import TeleopFrame, TeleopSession

logger = get_logger(__name__)

# DB 연결
engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def export_session(
    session_id: int,
    repo_id: str,
    root_dir: str | None = None,
    push_to_hub: bool = False,
):
    """세션 데이터를 LeRobot 데이터셋으로 내보내기.

    Args:
        session_id: 내보낼 세션 ID
        repo_id: Hugging Face 레포지토리 ID
        root_dir: 출력 디렉토리 (기본: ./lerobot_datasets)
        push_to_hub: Hub에 업로드 여부
    """
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset

    if root_dir is None:
        root_dir = "./lerobot_datasets"

    async with AsyncSessionLocal() as db:
        # 세션 정보 조회
        result = await db.execute(
            select(TeleopSession).where(TeleopSession.id == session_id)
        )
        teleop_session = result.scalar_one_or_none()

        if not teleop_session:
            logger.error("세션을 찾을 수 없습니다", session_id=session_id)
            return

        logger.info(
            "세션 내보내기 시작",
            session_id=session_id,
            robot_id=teleop_session.robot_id,
            repo_id=repo_id,
        )

        # 프레임 조회
        result = await db.execute(
            select(TeleopFrame)
            .where(TeleopFrame.session_id == session_id)
            .order_by(TeleopFrame.frame_index)
        )
        frames = result.scalars().all()

        if not frames:
            logger.warning("내보낼 프레임이 없습니다", session_id=session_id)
            return

        logger.info("프레임 로드 완료", count=len(frames))

        # Feature 정의 (첫 프레임 기반)
        first_data = frames[0].data
        features = {
            "observation.state": {
                "dtype": "float32",
                "shape": (len(first_data["observation"]),),
                "names": list(first_data["observation"].keys()),
            },
            "action": {
                "dtype": "float32",
                "shape": (len(first_data["action"]),),
                "names": list(first_data["action"].keys()),
            },
        }

        # 데이터셋 생성
        dataset = LeRobotDataset.create(
            repo_id=repo_id,
            fps=teleop_session.fps if teleop_session.fps else 30,
            features=features,
            robot_type=teleop_session.robot_id,
            root=root_dir,
            use_videos=False,  # 영상 포함 시 merge_dataset.py 사용
        )

        # 프레임 추가
        for frame in frames:
            obs_vals = [
                float(frame.data["observation"][k])
                for k in features["observation.state"]["names"]
            ]
            act_vals = [
                float(frame.data["action"][k])
                for k in features["action"]["names"]
            ]

            dataset.add_frame({
                "observation.state": torch.tensor(obs_vals, dtype=torch.float32),
                "action": torch.tensor(act_vals, dtype=torch.float32),
            })

        # 에피소드 저장
        dataset.save_episode()
        dataset.finalize()

        output_path = Path(root_dir) / repo_id
        logger.info("내보내기 완료", output_path=str(output_path))

        # Hub 업로드
        if push_to_hub:
            logger.info("Hugging Face Hub 업로드 시작")
            dataset.push_to_hub()
            logger.info("Hub 업로드 완료")

        print(f"\n내보내기 완료!")
        print(f"  세션 ID: {session_id}")
        print(f"  프레임 수: {len(frames)}")
        print(f"  출력 경로: {output_path}")

        if not push_to_hub:
            print("\nTip: Hub에 업로드하려면 --push 플래그를 추가하세요.")
        print("\nTip: 영상 포함 내보내기는 다음 명령어를 사용하세요:")
        print(f"  python -m scripts.merge_dataset --session_id {session_id} --repo_id {repo_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="LeRobot 데이터셋 내보내기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 관절값만 내보내기
    python export_to_dataset.py --session_id 1 --repo_id user/dataset

    # 출력 디렉토리 지정
    python export_to_dataset.py --session_id 1 --repo_id user/dataset --root ./my_datasets

    # Hub에 업로드
    python export_to_dataset.py --session_id 1 --repo_id user/dataset --push
        """,
    )
    parser.add_argument(
        "--session_id",
        type=int,
        required=True,
        help="내보낼 세션 ID",
    )
    parser.add_argument(
        "--repo_id",
        type=str,
        required=True,
        help="Hugging Face 레포지토리 ID (예: user/dataset)",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=None,
        help="출력 디렉토리 (기본: ./lerobot_datasets)",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Hugging Face Hub에 업로드",
    )

    args = parser.parse_args()

    asyncio.run(
        export_session(
            args.session_id,
            args.repo_id,
            args.root,
            args.push,
        )
    )
