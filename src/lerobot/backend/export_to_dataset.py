import asyncio
import argparse
import json
import torch
import numpy as np
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from lerobot.backend.models import TeleopSession, TeleopFrame
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.backend.database import DATABASE_URL

# Setup DB Connection (Must match database.py)
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

async def export_session(session_id: int, repo_id: str, root_dir: str):
    async with AsyncSessionLocal() as db_session:
        # Fetch Session Info
        result = await db_session.execute(select(TeleopSession).where(TeleopSession.id == session_id))
        teleop_session = result.scalar_one_or_none()
        
        if not teleop_session:
            print(f"Session {session_id} not found!")
            return

        print(f"Exporting Session {session_id} (Robot: {teleop_session.robot_id}) to {repo_id}...")

        # Fetch Frames
        result = await db_session.execute(
            select(TeleopFrame).where(TeleopFrame.session_id == session_id).order_by(TeleopFrame.frame_index)
        )
        frames = result.scalars().all()
        print(f"Found {len(frames)} frames.")

        if not frames:
            print("No frames to export.")
            return

        # Prepare Features (Simplified: Inference from first frame)
        # In production, this should be stored in meta_info or inferred robustly
        first_data = frames[0].data
        # Mock features structure required by LeRobotDataset
        features = {
            "observation.state": {
                "dtype": "float32",
                "shape": (len(first_data["observation"]),), 
                "names": list(first_data["observation"].keys())
            },
            "action": {
                "dtype": "float32",
                "shape": (len(first_data["action"]),),
                "names": list(first_data["action"].keys())
            }
        }
        
        # Create Dataset
        dataset = LeRobotDataset.create(
            repo_id=repo_id,
            fps=teleop_session.fps if teleop_session.fps else 30,
            features=features,
            robot_type=teleop_session.robot_id,
            root=root_dir,
            use_videos=False # We are only exporting state for now
        )

        # Populate Dataset
        for frame in frames:
            # Flatten dicts to list based on feature keys order
            obs_vals = [float(frame.data["observation"][k]) for k in features["observation.state"]["names"]]
            act_vals = [float(frame.data["action"][k]) for k in features["action"]["names"]]
            
            dataset.add_frame({
                "observation.state": torch.tensor(obs_vals),
                "action": torch.tensor(act_vals)
            })
        
        # Save Episode
        dataset.save_episode()
        dataset.finalize()
        print(f"Export Complete! Check {root_dir}/{repo_id}")

        # Optional: Push to Hub
        # dataset.push_to_hub()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session_id", type=int, required=True, help="Database Session ID to export")
    parser.add_argument("--repo_id", type=str, required=True, help="Hugging Face Repo ID (e.g. user/dataset)")
    parser.add_argument("--root", type=str, default=None, help="Root directory for dataset")
    
    args = parser.parse_args()
    
    asyncio.run(export_session(args.session_id, args.repo_id, args.root))
