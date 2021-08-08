CUDA_VISIBLE_DEVICES=0,1 python new_main.py \
  --synthetic_train_data_dir ../text_recognition_datasets/hand_written/lines_youkonge/all \
  --test_data_dir ../text_recognition_datasets/hand_written/lines_youkonge/te \
  --batch_size 32 \
  --workers 4 \
  --arch ResNet_IAM \
  --decode_type Attention \
  --with_lstm \
  --height 192 \
  --width 2048 \
  --max_len 128 \
  --epoch 150 \
  --punc \
  --padresize \
  --evaluation_metric word_accuracy \
  --augmentation IAM \
  --alphabets allcases \