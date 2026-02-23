# TO DO

- Remove devbox-connect. Instead, make it easy to copy an ssh tunnel command to expose all ports of all services to a remote box: `ssh -L 9000:localhost:9000 payne@dev.payne.io, etc.
- tool.uv.sources should be in cli, not in castle-api
- Add a scripts dir?
- Maybe there's no real reason to have special handling for the `tools` dir (one md file per tool, put in categories, etc.). On the one hand, the categories help them share dependencies. On the other, there's not really a need to share dependencies because uv does just fine. Also, they prob don't need markdown files because their description can just be in the --help arg, and in the `castle.yaml` registration. Having them flat would allow us to just think of everything as a tool: a bash script tool, a python tool, a rust tool. They're all things just follow a std-in std-out pattern so they are unix-philosophy good. Daemons otoh, follow daemon patterns (env config, logging, long-running, port mapping, etc.)


- tools: use std-in/std-out unix philosophy
- daemons or web-services: expose ports
- workers: just keep doing work in a background--usually watching the filesystem or a queue
- jobs: scheduled tools or daemon requests
- frontend: files served up by caddy
