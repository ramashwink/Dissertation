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
            'swarm_heartbeat = swarm_discovery.swarm_heartbeat:main',
            'swarm_registry = swarm_discovery.swarm_registry:main',
            'coop_loc_dynamic = swarm_discovery.cooperative_localisation_dynamic:main',
            'sybil_registry_attack = swarm_discovery.sybil_registry_attack:main',
            'swarm_viz = swarm_discovery.swarm_viz:main',
        ],
    },
)
