#!/usr/bin/env python3
"""Run host-only input, settings, startup and package tests. No TV required."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def main():
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=os.pathsep.join(map(str,[ROOT/'src/runtime',ROOT/'tests'])))
    subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(ROOT/'tests'),'-p','test_*.py'],env=env,check=True,cwd=ROOT)
    for test in sorted((ROOT/'tests').glob('test_*.js')):
        subprocess.run(['node',str(test)],cwd=ROOT,check=True)
    print('Host checks complete. They do not establish compatibility with a new TV.')
if __name__=='__main__':main()
