from setuptools import setup

package_name = 'swarm_discovery'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Ashwin Kotharamath',
    maintainer_email='se25272@bristol.ac.uk',
    description='Dynamic swarm discovery stack',
    license='MIT',
    entry_points={
        'console_scripts': [
            # ── Discovery / membership ───────────────────────────────────────
            'swarm_heartbeat          = swarm_discovery.swarm_heartbeat:main',
            'swarm_registry           = swarm_discovery.swarm_registry:main',
            'swarm_registry_service   = swarm_discovery.swarm_registry_service:main',
            'swarm_client             = swarm_discovery.swarm_client:main',

            # ── Localisation algorithms ──────────────────────────────────────
            'coop_loc_dynamic         = swarm_discovery.cooperative_localisation_dynamic:main',
            'coop_loc_ekf             = swarm_discovery.cooperative_localisation_ekf:main',
            'coop_loc_wls_huber       = swarm_discovery.coop_loc_wls_huber:main',
            'coop_loc_wls_tukey       = swarm_discovery.coop_loc_wls_tukey:main',
            'coop_loc_ransac          = swarm_discovery.coop_loc_ransac:main',
            'coop_loc_ekf_chi2_huber  = swarm_discovery.coop_loc_ekf_chi2_huber:main',

            # ── Logging ──────────────────────────────────────────────────────
            'coop_loc_logger          = swarm_discovery.coop_loc_logger:main',
            'ekf_attack_logger        = swarm_discovery.ekf_attack_logger:main',

            # ── Attacks ──────────────────────────────────────────────────────
            'sybil_registry_attack    = swarm_discovery.sybil_registry_attack:main',
            'sybil_service_attack     = swarm_discovery.sybil_service_attack:main',
            'sybil_consistent_attack  = swarm_discovery.sybil_consistent_attack:main',
            'replay_attack            = swarm_discovery.replay_attack:main',
            'replay_attack_gradual    = swarm_discovery.replay_attack_gradual:main',
            'wormhole_attack          = swarm_discovery.wormhole_attack:main',
            'timesync_attack          = swarm_discovery.timesync_attack:main',
            'byzantine_insider_attack = swarm_discovery.byzantine_insider_attack:main',

            # ── Visualisation ────────────────────────────────────────────────
            'swarm_viz                = swarm_discovery.swarm_viz:main',
        ],
    },
)
