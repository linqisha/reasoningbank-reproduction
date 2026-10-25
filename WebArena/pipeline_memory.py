# Copyright 2026 Google LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import os
import json
import argparse
import sys
from subprocess import Popen
import random

from utils.reasoningbank_llm import chat_model_name, load_dotenv_if_present


def main():
    load_dotenv_if_present()
    if args.memory_mode != "no_memory":
        # 原版不建这个目录，run.py / induce_memory.py 直接 open 会 FileNotFoundError
        os.makedirs(f"memories_{args.memory_mode}", exist_ok=True)

    # collect examples
    config_files = [
        os.path.join("config_files", f) for f in os.listdir("config_files")
        if f.endswith(".json") and f.split(".")[0].isdigit()
    ]
    config_files = sorted(config_files, key=lambda x: int(x.split("/")[-1].split(".")[0]))
    config_list = [json.load(open(f)) for f in config_files]
    if args.website == "multi":
        config_flags = []
        for config in config_list:
            if len(config["sites"]) != 1 and "map" not in config['sites']:
                config_flags.append(True)
            else:
                config_flags.append(False)
    else:
        config_flags = [config["sites"] == [args.website] for config in config_list]
    task_ids = [config["task_id"] for config, flag in zip(config_list, config_flags) if flag]
    # random.shuffle(task_ids)

    if args.end_index == None: 
        args.end_index = len(task_ids)

    # num = args.output_dir.split("_")[-1]

    for tid in task_ids[args.start_index: args.end_index]:

        if int(tid) <= args.prev_id:
            continue

        # step 1: run inference
        run_cmd = [
            sys.executable, "run.py",
            "--task_name", f"webarena.{tid}",
            "--model_name", args.model,
            "--results_path", f"{args.output_dir}",
        ]
        if args.memory_mode != "no_memory":
            run_cmd += ["--memory_path", f"memories_{args.memory_mode}/{args.website}.txt"]
        process = Popen(run_cmd)
        process.wait()

        # step 2: run evaluation
        process = Popen([
            sys.executable, "-m", "autoeval.evaluate_trajectory",
            "--result_dir", f"{args.output_dir}/webarena.{tid}",
            "--model", args.model,
            "--log_dir", f"autoeval/logs_{args.memory_mode}_{args.website}",
        ])
        process.wait()

        if args.memory_mode == "no_memory":
            continue

        # step 3: extract new memory items
        process = Popen([
            sys.executable, "induce_memory.py",
            "--result_dir", args.output_dir,
            "--task", f"webarena.{tid}",
            "--criteria", args.judge,
            "--memory_mode", args.memory_mode,
            "--model", args.model,
            "--output_path", f"memories_{args.memory_mode}/{args.website}.jsonl"
        ])
        process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--website", type=str, required=True,
                        choices=["shopping", "shopping_admin", "gitlab", "reddit", "multi"])
    parser.add_argument("--start_index", type=int, default=0)
    parser.add_argument("--end_index", type=int, default=None)
    parser.add_argument("--output_dir", type=str, default=None)
    parser.add_argument("--model", type=str, default=chat_model_name(),
                        help="agent / judge / 记忆生成用的模型；未内置的名字走 OpenAI 兼容接口（RB_CHAT_*）")
    parser.add_argument("--prev_id", type=int, default=-1)
    parser.add_argument("--memory_mode", type=str, default="reasoningbank",
                        choices=["no_memory", "reasoningbank", "awm", "synapse"])
    parser.add_argument("--judge", type=str, default="autoeval")
    args = parser.parse_args()

    main()
