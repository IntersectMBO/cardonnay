"""Functionality for cluster scripts (starting and stopping clusters)."""

import dataclasses
import itertools
import logging
import pathlib as pl
import random
import typing as tp

from cardonnay import helpers
from cardonnay import ttypes

LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, order=True)
class InstanceFiles:
    start_script: pl.Path
    stop_script: pl.Path
    start_script_args: list[str]
    dir: pl.Path


@dataclasses.dataclass(frozen=True, order=True)
class NodePorts:
    num: int
    node: int
    ekg: int
    prometheus: int


@dataclasses.dataclass(frozen=True, order=True)
class InstancePorts:
    base: int
    webserver: int
    metrics_submit_api: int
    submit_api: int
    smash: int
    supervisor: int
    relay1: int
    ekg_relay1: int
    prometheus_relay1: int
    bft1: int
    ekg_bft1: int
    prometheus_bft1: int
    pool1: int
    ekg_pool1: int
    prometheus_pool1: int
    pool2: int
    ekg_pool2: int
    prometheus_pool2: int
    pool3: int
    ekg_pool3: int
    prometheus_pool3: int
    node_ports: tuple[NodePorts, ...]


class LocalScripts:
    """Scripts for starting local cluster."""

    def __init__(self, num_pools: int, scripts_dir: pl.Path, ports_base: int) -> None:
        self.num_pools = num_pools
        self.scripts_dir = scripts_dir
        self.ports_base = ports_base

    def get_instance_ports(self, instance_num: int) -> InstancePorts:
        """Return ports mapping for given cluster instance."""
        # Allocate 100 ports per each 18 pools
        ports_per_instance = ((self.num_pools - 1) // 18 + 1) * 100
        offset = instance_num * ports_per_instance
        base = self.ports_base + offset
        last_port = base + ports_per_instance - 1
        ports_per_node = 5

        def _get_node_ports(num: int) -> NodePorts:
            rec_base = base + (num * ports_per_node)
            return NodePorts(
                num=num,
                node=rec_base,
                ekg=rec_base + 1,
                prometheus=rec_base + 2,
            )

        node_ports = tuple(_get_node_ports(i) for i in range(self.num_pools + 1))  # +1 for BFT node

        ports = InstancePorts(
            base=base,
            webserver=last_port,
            metrics_submit_api=last_port - 1,
            submit_api=last_port - 2,
            smash=last_port - 3,
            supervisor=12001 + instance_num,
            # Relay1
            relay1=0,
            ekg_relay1=0,
            prometheus_relay1=0,
            # Bft1
            bft1=base,
            ekg_bft1=base + 1,
            prometheus_bft1=base + 2,
            # Pool1
            pool1=base + 5,
            ekg_pool1=base + 6,
            prometheus_pool1=base + 7,
            # Pool2
            pool2=base + 10,
            ekg_pool2=base + 11,
            prometheus_pool2=base + 12,
            # Pool3
            pool3=base + 15,
            ekg_pool3=base + 16,
            prometheus_pool3=base + 17,
            # All nodes
            node_ports=node_ports,
        )
        return ports

    def _replace_node_template(
        self, template_file: pl.Path, node_rec: NodePorts, instance_num: int
    ) -> str:
        """Replace template variables in given content."""
        content = template_file.read_text(encoding="utf-8")
        new_content = content.replace("%%POOL_NUM%%", str(node_rec.num))
        new_content = new_content.replace("%%INSTANCE_NUM%%", str(instance_num))
        new_content = new_content.replace("%%NODE_PORT%%", str(node_rec.node))
        new_content = new_content.replace("%%EKG_PORT%%", str(node_rec.ekg))
        new_content = new_content.replace("%%PROMETHEUS_PORT%%", str(node_rec.prometheus))
        return new_content

    def _replace_instance_files(
        self, infile: pl.Path, instance_ports: InstancePorts, instance_num: int, ports_per_node: int
    ) -> str:
        """Replace instance variables in given content."""
        content = infile.read_text(encoding="utf-8")
        # Replace cluster instance number
        new_content = content.replace("%%INSTANCE_NUM%%", str(instance_num))
        # Replace number of pools
        new_content = new_content.replace("%%NUM_POOLS%%", str(self.num_pools))
        # Replace node port number strings
        new_content = new_content.replace("%%NODE_PORT_BASE%%", str(instance_ports.base))
        # Replace number of reserved ports per node
        new_content = new_content.replace("%%PORTS_PER_NODE%%", str(ports_per_node))
        # Reconfigure supervisord port
        new_content = new_content.replace("%%SUPERVISOR_PORT%%", str(instance_ports.supervisor))
        # Reconfigure submit-api port
        new_content = new_content.replace("%%SUBMIT_API_PORT%%", str(instance_ports.submit_api))
        # Reconfigure submit-api metrics port
        new_content = new_content.replace(
            "%%METRICS_SUBMIT_API_PORT%%", str(instance_ports.metrics_submit_api)
        )
        # Reconfigure smash port
        new_content = new_content.replace("%%SMASH_PORT%%", str(instance_ports.smash))
        # Reconfigure webserver port
        new_content = new_content.replace("%%WEBSERVER_PORT%%", str(instance_ports.webserver))
        return new_content

    def _gen_legacy_topology(self, addr: str, ports: tp.Iterable[int]) -> dict:
        """Generate legacy topology for given ports."""
        producers = [
            {
                "addr": addr,
                "port": port,
                "valency": 1,
            }
            for port in ports
        ]
        topology = {"Producers": producers}
        return topology

    def _gen_p2p_topology(self, addr: str, ports: list[int], fixed_ports: list[int]) -> dict:
        """Generate p2p topology for given ports."""
        # Select fixed ports and several randomly selected ports
        rand_threshold = 3
        sample_ports = random.sample(ports, 3) if len(ports) > rand_threshold else ports
        selected_ports = set(fixed_ports + sample_ports)
        access_points = [{"address": addr, "port": port} for port in selected_ports]
        topology = {
            "localRoots": [
                {"accessPoints": access_points, "advertise": False, "valency": len(access_points)},
            ],
            "publicRoots": [],
            "useLedgerAfterSlot": -1,
        }
        return topology

    def _gen_supervisor_conf(self, instance_num: int, instance_ports: InstancePorts) -> str:
        """Generate supervisor configuration for given instance."""
        lines = [
            "# [inet_http_server]",
            f"# port=127.0.0.1:{instance_ports.supervisor}",
        ]

        programs = []
        for node_rec in instance_ports.node_ports:
            node_name = "bft1" if node_rec.num == 0 else f"pool{node_rec.num}"

            programs.append(node_name)

            lines.extend(
                [
                    f"\n[program:{node_name}]",
                    f"command=./state-cluster{instance_num}/cardano-node-{node_name}",
                    f"stderr_logfile=./state-cluster{instance_num}/{node_name}.stderr",
                    f"stdout_logfile=./state-cluster{instance_num}/{node_name}.stdout",
                    "startsecs=5",
                ]
            )

        lines.extend(
            [
                "\n[group:nodes]",
                f"programs={','.join(programs)}",
                "\n[program:webserver]",
                f"command=python -m http.server --bind 127.0.0.1 {instance_ports.webserver}",
                f"directory=./state-cluster{instance_num}/webserver",
                "\n[rpcinterface:supervisor]",
                "supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface",
                "\n[supervisorctl]",
                "\n[supervisord]",
                f"logfile=./state-cluster{instance_num}/supervisord.log",
                f"pidfile=./state-cluster{instance_num}/supervisord.pid",
            ]
        )

        return "\n".join(lines)

    def _gen_topology_files(
        self, destdir: pl.Path, addr: str, nodes: tp.Sequence[NodePorts]
    ) -> None:
        """Generate topology files for all nodes."""
        all_nodes = [p.node for p in nodes]

        for node_rec in nodes:
            all_except = all_nodes[:]
            all_except.remove(node_rec.node)
            node_name = "bft1" if node_rec.num == 0 else f"pool{node_rec.num}"

            # Legacy topology

            topology = self._gen_legacy_topology(addr=addr, ports=all_except)
            helpers.write_json(out_file=destdir / f"topology-{node_name}.json", content=topology)

            # P2P topology

            # Bft1 and first three pools
            fixed_ports = all_except[:4]

            p2p_topology = self._gen_p2p_topology(
                addr=addr, ports=all_except, fixed_ports=fixed_ports
            )

            helpers.write_json(
                out_file=destdir / f"p2p-topology-{node_name}.json", content=p2p_topology
            )

    def _reconfigure_local(self, indir: pl.Path, destdir: pl.Path, instance_num: int) -> None:
        """Reconfigure cluster scripts and config files."""
        instance_ports = self.get_instance_ports(instance_num=instance_num)
        ports_per_node = instance_ports.pool1 - instance_ports.bft1
        addr = "127.0.0.1"
        common_dir = indir.parent / "common"

        # Reconfigure cluster instance files
        for infile in itertools.chain(common_dir.glob("*"), indir.glob("*")):
            fname = infile.name

            # Skip template files
            if fname.startswith("template-"):
                continue

            outfile = destdir / fname
            dest_content = self._replace_instance_files(
                infile=infile,
                instance_ports=instance_ports,
                instance_num=instance_num,
                ports_per_node=ports_per_node,
            )
            outfile.unlink(missing_ok=True)
            outfile.write_text(f"{dest_content}\n", encoding="utf-8")

            # Make `*.sh` files and files without extension executable
            if "." not in fname or fname.endswith(".sh"):
                outfile.chmod(0o755)

        # Generate config and topology files from templates
        for node_rec in instance_ports.node_ports:
            if node_rec.num != 0:
                supervisor_script = destdir / f"cardano-node-pool{node_rec.num}"
                supervisor_script_content = self._replace_node_template(
                    template_file=indir / "template-cardano-node-pool",
                    node_rec=node_rec,
                    instance_num=instance_num,
                )
                supervisor_script.unlink(missing_ok=True)
                supervisor_script.write_text(f"{supervisor_script_content}\n", encoding="utf-8")
                supervisor_script.chmod(0o755)

            node_name = "bft1" if node_rec.num == 0 else f"pool{node_rec.num}"
            node_config = destdir / f"config-{node_name}.json"
            node_config_content = self._replace_node_template(
                template_file=indir / "template-config.json",
                node_rec=node_rec,
                instance_num=instance_num,
            )
            node_config.unlink(missing_ok=True)
            node_config.write_text(f"{node_config_content}\n", encoding="utf-8")

        self._gen_topology_files(destdir=destdir, addr=addr, nodes=instance_ports.node_ports)

        supervisor_conf_file = destdir / "supervisor.conf"
        supervisor_conf_content = self._gen_supervisor_conf(
            instance_num=instance_num, instance_ports=instance_ports
        )
        supervisor_conf_file.unlink(missing_ok=True)
        supervisor_conf_file.write_text(f"{supervisor_conf_content}\n", encoding="utf-8")

    def prepare_scripts_files(
        self,
        destdir: pl.Path,
        instance_num: int,
        scriptsdir: ttypes.FileType = "",
    ) -> InstanceFiles:
        """Prepare scripts files for starting and stopping cluster instance."""
        destdir = destdir.expanduser().resolve()
        scriptsdir_final = pl.Path(scriptsdir or self.scripts_dir)

        self._reconfigure_local(indir=scriptsdir_final, destdir=destdir, instance_num=instance_num)

        return InstanceFiles(
            start_script=destdir / "start-cluster",
            stop_script=destdir / "stop-cluster",
            start_script_args=[],
            dir=destdir,
        )


def prepare_scripts_files(
    destdir: pl.Path,
    scriptsdir: pl.Path,
    instance_num: int,
    num_pools: int,
    ports_base: int,
) -> InstanceFiles:
    """Prepare scripts files for starting and stopping cluster instance."""
    testnet_path = scriptsdir / "testnet.json"
    if not testnet_path:
        msg = f"Testnet file not found in '{scriptsdir}'."
        raise RuntimeError(msg)

    local_scripts = LocalScripts(num_pools=num_pools, scripts_dir=scriptsdir, ports_base=ports_base)
    startup_files = local_scripts.prepare_scripts_files(
        destdir=destdir,
        instance_num=instance_num,
        scriptsdir=scriptsdir,
    )
    return startup_files
