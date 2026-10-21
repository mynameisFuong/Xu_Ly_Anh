$ErrorActionPreference = "Stop"

# dlib-bin provides maintained Windows wheels, including Python 3.14.
python -m pip install "dlib-bin==20.0.1.post1" "face-recognition-models==0.3.0" "Pillow>=11" "click>=8" "setuptools<81"
# The upstream package declares `dlib`; --no-deps prevents rebuilding it after
# the compatible dlib-bin wheel above has already provided the `dlib` module.
python -m pip install "face-recognition==1.3.0" --no-deps

python -c "from ai_pipeline.recognition import FaceRecognizer; r=FaceRecognizer(); assert r.supports_pose; print('Face ID engine ready:', r.model_name)"
