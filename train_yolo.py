"""
train_yolo.py
=============
Fine-tune a YOLO detector on the Valorant enemy-head dataset built by
prepare_dataset.py.

Run (inside the 3.12 venv that has ultralytics + CUDA torch):
    .venv\\Scripts\\python train_yolo.py
    .venv\\Scripts\\python train_yolo.py --model yolo11s.pt --epochs 150 --imgsz 1280

DATA REALITY (read before trusting the numbers):
  - All frames come from ONE clip → train and val share the same map, agents,
    and lighting. The temporal split reduces leakage but val metrics will still
    be OPTIMISTIC vs. unseen footage. Treat this as a proof-of-concept pipeline;
    add more clips to dataset/ for a model that generalises.
  - Heads are ~20px in a 2560x1440 frame. We train at imgsz=1280 so a head is
    ~10px after resize — small-object regime. Going below 1280 will hurt recall.
"""

import argparse

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser(description="Train YOLO on enemy heads")
    parser.add_argument("--model",  default="yolo11n.pt",
                        help="Pretrained checkpoint (yolo11n/yolo11s/yolov8n...)")
    parser.add_argument("--data",   default="data.yaml")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--imgsz",  type=int, default=1280)
    parser.add_argument("--batch",  type=int, default=4,
                        help="Lower if you hit CUDA out-of-memory at imgsz 1280")
    parser.add_argument("--patience", type=int, default=30,
                        help="Early-stop after N epochs without val improvement")
    parser.add_argument("--name",   default="heads_v1")
    args = parser.parse_args()

    model = YOLO(args.model)

    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=args.patience,
        name=args.name,
        # Small-object friendly: keep boxes, soften aggressive geometric aug that
        # can push a 20px head out of frame.
        scale=0.3,
        mosaic=0.5,
        close_mosaic=15,      # disable mosaic for last 15 epochs -> cleaner fine-tune
        device=0,             # RTX 4060 Ti
        plots=True,
    )

    # Validate best weights and print the headline metric.
    metrics = model.val(data=args.data, imgsz=args.imgsz)
    print("\n=== VALIDATION (best weights) ===")
    print(f"  mAP50    : {metrics.box.map50:.4f}")
    print(f"  mAP50-95 : {metrics.box.map:.4f}")
    print(f"  Precision: {metrics.box.mp:.4f}")
    print(f"  Recall   : {metrics.box.mr:.4f}")


if __name__ == "__main__":
    main()
