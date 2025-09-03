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
                wt_dir=$(ls -d "%s"*/dags/dbt/)
                rsync -r --links --no-perms --no-owner --no-group --delete --copy-links --keep-dirlinks --safe-links "$wt_dir" "%s"
            ]], event.source, event.target)
        )
    end,
    action = function(inlet)
        local elist = inlet.getEvents()
        if elist then
            local config = inlet.getConfig()
            spawn(elist, "/bin/bash", "-c", 
                string.format([[
                    wt_dir=$(ls -d "%s"*/dags/dbt/)
                    rsync -r --links --no-perms --no-owner --no-group --delete --copy-links --keep-dirlinks --safe-links "$wt_dir" "%s"
                ]], config.source, config.target)
            )
        end
    end
}

sync{
    bash,
    source = "/opt/airflow/dags/.worktrees",
    target = "/opt/airflow/dbt"
}