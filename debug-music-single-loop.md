# Debug Session: music-single-loop

- Status: [OPEN]
- Session ID: music-single-loop
- Started: 2026-08-27

## Problem Statement

- **Expected**: 切换到"单曲循环"模式后，当前歌曲播放结束应自动重播同一首。
- **Actual**: 单曲循环功能无效（用户反馈"依旧没修好"）。
- **Component**: `app/ui/music_player.py` — `MusicPlayer` 类的循环逻辑。

## Reproduction Steps (待用户确认)

1. 启动应用，打开音乐播放器
2. 上传/选择一首歌开始播放
3. 点击循环按钮切换到"单曲循环"模式（图标带 1）
4. 等待歌曲自然播放结束
5. 观察是否自动重播

## Known Code Paths

- `cycle_loop` (L1069-1077): 切换 loop=0/1/2
- `_apply_player_loops` (L904-906): setLoops(Infinite/Once)
- `_on_status` (L1079-1086): EndOfMedia 兜底
- `_replay_current_source` (L908-919): stop()+play() 重启

## Hypotheses

待 Step 2 填充。

## Instrumentation Plan

待 Step 3 填充。

## Evidence Log

待 Step 5+ 填充。
