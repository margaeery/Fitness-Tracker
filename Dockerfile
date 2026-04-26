FROM kivy/buildozer:latest

WORKDIR /home/user/hostcwd

ENTRYPOINT ["bash", "scripts/entrypoint.sh"]
