settings {
    logfile    = "/tmp/lsyncd.log",
    statusFile = "/tmp/lsyncd.status",
    nodaemon   = true,
    insist     = true
}

bash = {
    delay = 5,
    maxProcesses = 1,
    init = function(event)
        spawn(event, "/bin/bash", "-c", 
            string.format([[
                # Find the most recently modified worktree (sorted by modification time, newest first)
                wt_dir=$(ls -dt "%s"*/dags/dbt/ 2>/dev/null | head -n 1)
                if [ -n "$wt_dir" ] && [ -d "$wt_dir" ]; then
                    rsync -r --links --no-perms --no-owner --no-group --delete --copy-links --keep-dirlinks --safe-links "$wt_dir" "%s"
                else
                    echo "Warning: No valid worktree directory found at %s"
                fi
            ]], event.source, event.target, event.source)
        )
    end,
    action = function(inlet)
        local elist = inlet.getEvents()
        if elist then
            local config = inlet.getConfig()
            spawn(elist, "/bin/bash", "-c", 
                string.format([[
                    # Find the most recently modified worktree (sorted by modification time, newest first)
                    wt_dir=$(ls -dt "%s"*/dags/dbt/ 2>/dev/null | head -n 1)
                    if [ -n "$wt_dir" ] && [ -d "$wt_dir" ]; then
                        rsync -r --links --no-perms --no-owner --no-group --delete --copy-links --keep-dirlinks --safe-links "$wt_dir" "%s"
                    else
                        echo "Warning: No valid worktree directory found at %s"
                    fi
                ]], config.source, config.target, config.source)
            )
        end
    end
}

sync{
    bash,
    source = "/opt/airflow/dags/.worktrees",
    target = "/opt/airflow/dbt"
}