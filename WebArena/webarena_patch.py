# coding=utf-8
# Copyright 2026 The Google Research Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Legacy shim for MemEvol-lenient llm_fuzzy_match.

This module used to monkey-patch webarena's helper_functions.llm_fuzzy_match
with a MemEvol-style lenient prompt. The vendored webarena tree at
third_party/webarena/ now carries that prompt inline, so the monkey-patch is
redundant; kept as a no-op only for import compatibility with run.py.

Usage:
    import webarena_patch  # noqa: F401
"""
